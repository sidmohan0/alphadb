"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AgentStatus, TerminalMessage } from "@/lib/skills/types"
import { executeSkill } from "@/lib/skills/executor"
import { TerminalHeader } from "./terminal-header"
import { TerminalMessages } from "./terminal-messages"
import { TerminalInput } from "./terminal-input"
import { cn } from "@/lib/utils"

type TerminalState = "minimized" | "compact" | "expanded"

function formatTime(date: Date): string {
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

function createMessage(
  type: TerminalMessage["type"],
  content: string,
  skillId?: string
): TerminalMessage {
  const now = new Date()
  return {
    id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
    type,
    content,
    timestamp: now,
    formattedTime: formatTime(now),
    skillId,
  }
}

export function AgentTerminal() {
  const [state, setState] = useState<TerminalState>("compact")
  const [status, setStatus] = useState<AgentStatus>("idle")
  const [messages, setMessages] = useState<TerminalMessage[]>([])
  const [inputHistory, setInputHistory] = useState<string[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([
    "status",
    "list strategies",
    "show data views",
    "lab insights",
  ])
  
  const inputRef = useRef<HTMLInputElement>(null)

  // Global keyboard shortcut: / to focus terminal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // / key focuses terminal (when not in an input)
      if (e.key === "/" && !["INPUT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault()
        if (state === "minimized") {
          setState("compact")
        }
        setTimeout(() => inputRef.current?.focus(), 50)
      }
      
      // Escape minimizes
      if (e.key === "Escape" && document.activeElement === inputRef.current) {
        inputRef.current?.blur()
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [state])

  const handleSubmit = useCallback(async (input: string) => {
    // Add human message
    setMessages((prev) => [...prev, createMessage("human", input)])
    setInputHistory((prev) => [...prev, input])
    
    // Set thinking state
    setStatus("thinking")
    
    // Auto-expand if minimized
    if (state === "minimized") {
      setState("compact")
    }
    
    try {
      const { skill, result } = await executeSkill(input)
      
      // Add skill invocation message (if verbose mode wanted)
      if (skill) {
        setMessages((prev) => [...prev, createMessage("skill", `invoking ${skill}`, skill)])
      }
      
      setStatus("acting")
      await new Promise((resolve) => setTimeout(resolve, 200))
      
      // Add result message
      const messageType = result.success ? "agent" : "error"
      setMessages((prev) => [...prev, createMessage(messageType, result.message)])
      
      // Add action confirmation if it was a mutation
      if (result.success && skill && ["pause", "resume", "stop"].some(cmd => skill.includes(cmd))) {
        const actionMsg = skill.replace(/_/g, " ").replace(/strategy/g, "").trim()
        setMessages((prev) => [...prev, createMessage("action", `${actionMsg} completed`)])
      }
      
      // Update suggestions
      if (result.suggestions) {
        setSuggestions(result.suggestions)
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        createMessage("error", "Something went wrong. Please try again."),
      ])
    } finally {
      setStatus("idle")
    }
  }, [state])

  const handleToggleExpand = () => {
    setState((prev) => (prev === "expanded" ? "compact" : "expanded"))
  }

  const handleMinimize = () => {
    setState((prev) => (prev === "minimized" ? "compact" : "minimized"))
  }

  const heights: Record<TerminalState, string> = {
    minimized: "h-10",
    compact: "h-36",
    expanded: "h-80",
  }

  return (
    <div
      className={cn(
        "bg-card/95 backdrop-blur border-t border-border transition-all duration-200 flex flex-col",
        heights[state]
      )}
    >
      <TerminalHeader
        status={status}
        isExpanded={state === "expanded"}
        isMinimized={state === "minimized"}
        onToggleExpand={handleToggleExpand}
        onMinimize={handleMinimize}
      />
      
      {state !== "minimized" && (
        <>
          <TerminalMessages messages={messages} />
          <TerminalInput
            ref={inputRef}
            onSubmit={handleSubmit}
            disabled={status === "thinking" || status === "acting"}
            suggestions={suggestions}
            history={inputHistory}
          />
        </>
      )}
    </div>
  )
}
