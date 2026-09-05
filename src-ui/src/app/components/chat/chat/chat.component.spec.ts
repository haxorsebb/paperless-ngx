import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http'
import { provideHttpClientTesting } from '@angular/common/http/testing'
import { ElementRef } from '@angular/core'
import { ComponentFixture, TestBed } from '@angular/core/testing'
import { NavigationEnd, Router } from '@angular/router'
import { RouterTestingModule } from '@angular/router/testing'
import { allIcons, NgxBootstrapIconsModule } from 'ngx-bootstrap-icons'
import { Subject } from 'rxjs'
import {
  CHAT_METADATA_DELIMITER,
  ChatService,
} from 'src/app/services/chat.service'
import { DocumentListViewService } from 'src/app/services/document-list-view.service'
import { ChatComponent } from './chat.component'

describe('ChatComponent', () => {
  let component: ChatComponent
  let fixture: ComponentFixture<ChatComponent>
  let chatService: ChatService
  let router: Router
  let routerEvents$: Subject<NavigationEnd>
  let mockStream$: Subject<string>
  let documentListViewService: {
    selected: Set<number>
    allSelected: boolean
  }

  beforeEach(async () => {
    documentListViewService = {
      selected: new Set<number>(),
      allSelected: false,
    }

    TestBed.configureTestingModule({
      imports: [
        NgxBootstrapIconsModule.pick(allIcons),
        RouterTestingModule,
        ChatComponent,
      ],
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        {
          provide: DocumentListViewService,
          useValue: documentListViewService,
        },
      ],
    }).compileComponents()

    fixture = TestBed.createComponent(ChatComponent)
    router = TestBed.inject(Router)
    routerEvents$ = new Subject<any>()
    jest
      .spyOn(router, 'events', 'get')
      .mockReturnValue(routerEvents$.asObservable())
    chatService = TestBed.inject(ChatService)
    mockStream$ = new Subject<string>()
    jest
      .spyOn(chatService, 'streamChat')
      .mockReturnValue(mockStream$.asObservable())
    component = fixture.componentInstance

    jest.useFakeTimers()

    fixture.detectChanges()

    component.scrollAnchor.nativeElement.scrollIntoView = jest.fn()
  })

  it('should update documentId on initialization', () => {
    jest.spyOn(router, 'url', 'get').mockReturnValue('/documents/123')
    component.ngOnInit()
    expect(component.documentId()).toBe(123)
  })

  it('should update documentId on navigation', () => {
    component.ngOnInit()
    routerEvents$.next(new NavigationEnd(1, '/documents/456', '/documents/456'))
    expect(component.documentId()).toBe(456)
  })

  it('should return correct placeholder based on document scope', () => {
    component.documentId.set(123)
    expect(component.placeholder).toBe('Ask a question about this document...')

    component.documentId.set(undefined)
    documentListViewService.selected.add(17)
    documentListViewService.selected.add(23)
    expect(component.placeholder).toBe(
      'Ask a question about the selected documents...'
    )

    documentListViewService.selected.clear()
    expect(component.placeholder).toBe('Ask a question about a document...')
  })

  it('should describe selected document chat scope', () => {
    documentListViewService.selected.add(17)
    documentListViewService.selected.add(23)

    expect(component.selectedDocumentIds).toEqual([17, 23])
    expect(component.scopeDescription).toBe('Chat scope: 2 selected documents')

    fixture.detectChanges()
    expect(
      fixture.nativeElement.querySelector('[data-testid="chat-scope"]')
        .textContent
    ).toContain('Chat scope: 2 selected documents')
  })

  it('should send selected document IDs to chat', () => {
    documentListViewService.selected.add(17)
    documentListViewService.selected.add(23)
    component.input.set('Compare')

    component.sendMessage()

    expect(chatService.streamChat).toHaveBeenCalledWith(
      undefined,
      'Compare',
      [17, 23]
    )
  })

  it('should keep document detail scope authoritative over list selection', () => {
    documentListViewService.selected.add(23)
    documentListViewService.selected.add(41)
    component.documentId.set(17)
    component.input.set('Question')

    component.sendMessage()

    expect(component.selectedDocumentIds).toEqual([])
    expect(component.scopeDescription).toBe('Chat scope: this document')
    expect(chatService.streamChat).toHaveBeenCalledWith(
      17,
      'Question',
      undefined
    )
  })

  it('should not treat select-all filtered state as a concrete ID scope', () => {
    documentListViewService.selected.add(17)
    documentListViewService.selected.add(23)
    documentListViewService.allSelected = true
    component.input.set('Question')

    component.sendMessage()

    expect(component.selectedDocumentIds).toEqual([])
    expect(component.scopeDescription).toBe(
      'Chat scope: all permitted documents'
    )
    expect(chatService.streamChat).toHaveBeenCalledWith(
      undefined,
      'Question',
      undefined
    )
  })

  it('should send a message and render the streaming response', async () => {
    component.input.set('Hello')
    component.sendMessage()

    expect(component.messages()).toHaveLength(2)
    expect(component.messages()[0].content).toBe('Hello')
    expect(component.loading()).toBe(true)

    mockStream$.next('Hi')
    expect(component.messages()[1].content).toBe('H')
    mockStream$.next('Hi there')
    // advance time to process the typewriter effect
    await jest.runAllTimersAsync()
    await fixture.whenStable()
    expect(component.messages()[1].content).toBe('Hi there')
    expect(
      fixture.nativeElement.querySelector('.chat-messages').textContent
    ).toContain('Hi there')

    mockStream$.complete()
    await jest.runAllTimersAsync()
    await fixture.whenStable()
    expect(component.loading()).toBe(false)
    expect(component.messages()[1].isStreaming).toBe(false)
    expect(fixture.nativeElement.querySelector('#chatInput').disabled).toBe(
      false
    )
  })

  it('should parse references from the metadata trailer without showing it', () => {
    component.input.set('Hello')
    component.sendMessage()

    mockStream$.next(
      `Hi there${CHAT_METADATA_DELIMITER}{"references":[{"id":42,"title":"Bread Recipe"}]}`
    )
    jest.advanceTimersByTime(1000)

    expect(component.messages()[1].content).toBe('Hi there')
    expect(component.messages()[1].references).toEqual([
      { id: 42, title: 'Bread Recipe' },
    ])
  })

  it('should render document reference links under assistant messages', () => {
    component.input.set('Hello')
    component.sendMessage()

    mockStream$.next(
      `Hi there${CHAT_METADATA_DELIMITER}{"references":[{"id":42,"title":"Bread Recipe"}]}`
    )
    jest.advanceTimersByTime(1000)
    fixture.detectChanges()

    const link = fixture.nativeElement.querySelector('.chat-references a')
    expect(link.textContent).toContain('Bread Recipe')
    expect(link.getAttribute('href')).toContain('/documents/42')
  })

  it('should remove delimiter fragments that were already streamed', () => {
    component.input.set('Hello')
    component.sendMessage()

    mockStream$.next(`Hi there${CHAT_METADATA_DELIMITER.slice(0, 8)}`)
    jest.advanceTimersByTime(1000)
    expect(component.messages()[1].content).toBe(
      `Hi there${CHAT_METADATA_DELIMITER.slice(0, 8)}`
    )

    mockStream$.next(
      `Hi there${CHAT_METADATA_DELIMITER}{"references":[{"id":42,"title":"Bread Recipe"}]}`
    )
    jest.advanceTimersByTime(1000)

    expect(component.messages()[1].content).toBe('Hi there')
    expect(component.messages()[1].references).toEqual([
      { id: 42, title: 'Bread Recipe' },
    ])
  })

  it('should handle errors during streaming', () => {
    component.input.set('Hello')
    component.sendMessage()

    mockStream$.error('Error')
    expect(component.messages()[1].content).toContain(
      '⚠️ Error receiving response.'
    )
    expect(component.loading()).toBe(false)
  })

  it('should enqueue typewriter chunks correctly', () => {
    const message = { content: '', role: 'assistant', isStreaming: true }
    component.enqueueTypewriter(null, message as any) // coverage for null
    component.enqueueTypewriter('Hello', message as any)
    expect(component['typewriterBuffer']).toHaveLength(4)
  })

  it('should scroll to bottom after sending a message', () => {
    const scrollSpy = jest.spyOn(
      ChatComponent.prototype as any,
      'scrollToBottom'
    )
    component.input.set('Test')
    component.sendMessage()
    expect(scrollSpy).toHaveBeenCalled()
  })

  it('should focus chat input when dropdown is opened', () => {
    const focus = jest.fn()
    component.chatInput = {
      nativeElement: { focus: focus },
    } as unknown as ElementRef<HTMLInputElement>

    component.onOpenChange(true)
    jest.advanceTimersByTime(15)
    expect(focus).toHaveBeenCalled()
  })

  it('should send message on Enter key press', () => {
    jest.spyOn(component, 'sendMessage')
    const event = new KeyboardEvent('keydown', { key: 'Enter' })
    component.searchInputKeyDown(event)
    expect(component.sendMessage).toHaveBeenCalled()
  })

  it('should not send message on Enter key press while composing with IME', () => {
    jest.spyOn(component, 'sendMessage')
    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      isComposing: true,
    })
    component.searchInputKeyDown(event)
    expect(component.sendMessage).not.toHaveBeenCalled()
  })
})
