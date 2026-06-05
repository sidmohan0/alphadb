"use client"

import { TerminalMessage } from "@/lib/skills/types"
import { cn } from "@/lib/utils"
import { useEffect, useRef } from "react"

interface TerminalMessagesProps {
  messages: TerminalMessage[]
}

export function TerminalMessages({ messages }: TerminalMessagesProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const getMessageStyles = (type: TerminalMessage["type"]) => {
    switch (type) {
      case "human":
        return "text-foreground"
      case "agent":
        return "text-foreground/90"
      case "action":
        return "text-amber-500 font-mono"
      case "error":
        return "text-destructive"
      case "suggestion":
        return "text-muted-foreground italic"
      case "skill":
        return "text-muted-foreground/60 font-mono text-[11px]"
      default:
        return "text-foreground"
    }
  }

  const formatContent = (message: TerminalMessage) => {
    const lines = message.content.split("\n")
    
    if (message.type === "action") {
      return `[${message.content}]`
    }
    
    if (message.type === "skill") {
      return `→ ${message.content}`
    }
    
    if (message.type === "human") {
      return (
        <span>
          <span className="text-primary">You:</span> {message.content}
        </span>
      )
    }
    
    if (message.type === "agent" && lines.length > 1) {
      return (
        <span>
          <span className="text-muted-foreground">Agent:</span>{" "}
          {lines.map((line, i) => (
            <span key={i}>
              {i > 0 && <br />}
              {i > 0 && <span className="inline-block w-[3.5rem]" />}
              {line}
            </span>
          ))}
        </span>
      )
    }
    
    if (message.type === "agent") {
      return (
        <span>
          <span className="text-muted-foreground">Agent:</span> {message.content}
        </span>
      )
    }
    
    return message.content
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Type a command or ask a question...
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-1.5 font-mono text-sm">
      {messages.map((message) => (
        <div key={message.id} className="flex items-start gap-3">
          <span className="text-muted-foreground/60 text-xs w-10 shrink-0 pt-0.5">
            {message.formattedTime}
          </span>
          <div className={cn("flex-1 whitespace-pre-wrap", getMessageStyles(message.type))}>
            {formatContent(message)}
          </div>
        </div>
      ))}
    </div>
  )
}
