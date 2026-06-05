"use client"

import { cn } from "@/lib/utils"
import { ChevronRight, CornerDownLeft } from "lucide-react"
import { forwardRef, KeyboardEvent, useCallback, useState } from "react"

interface TerminalInputProps {
  onSubmit: (input: string) => void
  disabled?: boolean
  suggestions?: string[]
  history: string[]
}

export const TerminalInput = forwardRef<HTMLInputElement, TerminalInputProps>(
  function TerminalInput({ onSubmit, disabled, suggestions = [], history }, ref) {
    const [value, setValue] = useState("")
    const [historyIndex, setHistoryIndex] = useState(-1)
    const [showSuggestions, setShowSuggestions] = useState(false)

    const handleSubmit = useCallback(() => {
      if (value.trim() && !disabled) {
        onSubmit(value.trim())
        setValue("")
        setHistoryIndex(-1)
        setShowSuggestions(false)
      }
    }, [value, disabled, onSubmit])

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault()
        handleSubmit()
      } else if (e.key === "ArrowUp") {
        e.preventDefault()
        if (history.length > 0) {
          const newIndex = historyIndex < history.length - 1 ? historyIndex + 1 : historyIndex
          setHistoryIndex(newIndex)
          setValue(history[history.length - 1 - newIndex] || "")
        }
      } else if (e.key === "ArrowDown") {
        e.preventDefault()
        if (historyIndex > 0) {
          const newIndex = historyIndex - 1
          setHistoryIndex(newIndex)
          setValue(history[history.length - 1 - newIndex] || "")
        } else if (historyIndex === 0) {
          setHistoryIndex(-1)
          setValue("")
        }
      } else if (e.key === "Tab" && suggestions.length > 0) {
        e.preventDefault()
        setValue(suggestions[0])
      } else if (e.key === "Escape") {
        setValue("")
        setShowSuggestions(false)
      }
    }

    const handleSuggestionClick = (suggestion: string) => {
      setValue(suggestion)
      setShowSuggestions(false)
    }

    const filteredSuggestions = suggestions.filter(s => 
      s.toLowerCase().includes(value.toLowerCase())
    )

    return (
      <div className="relative">
        {showSuggestions && value && filteredSuggestions.length > 0 && (
          <div className="absolute bottom-full left-0 right-0 mb-1 bg-card border border-border rounded-md shadow-lg overflow-hidden">
            {filteredSuggestions.slice(0, 5).map((suggestion, i) => (
              <button
                key={i}
                onClick={() => handleSuggestionClick(suggestion)}
                className={cn(
                  "w-full px-3 py-1.5 text-left text-sm font-mono",
                  "hover:bg-muted transition-colors",
                  "flex items-center gap-2"
                )}
              >
                <ChevronRight className="h-3 w-3 text-muted-foreground" />
                {suggestion}
              </button>
            ))}
          </div>
        )}
        
        <div className="flex items-center gap-2 px-3 py-2 border-t border-border bg-background/50">
          <span className="text-primary font-mono text-sm">{">"}</span>
          <input
            ref={ref}
            type="text"
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              setShowSuggestions(true)
              setHistoryIndex(-1)
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
            placeholder="Type a command or ask a question..."
            disabled={disabled}
            className={cn(
              "flex-1 bg-transparent text-foreground font-mono text-sm",
              "placeholder:text-muted-foreground/50",
              "focus:outline-none",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !value.trim()}
            className={cn(
              "p-1 rounded transition-colors",
              value.trim()
                ? "text-primary hover:bg-primary/10"
                : "text-muted-foreground/30"
            )}
            title="Send (Enter)"
          >
            <CornerDownLeft className="h-4 w-4" />
          </button>
        </div>
      </div>
    )
  }
)
