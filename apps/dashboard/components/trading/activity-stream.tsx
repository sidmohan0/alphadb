'use client'

import { ScrollArea } from '@/components/ui/scroll-area'

export interface ActivityEvent {
  id: string
  time?: string // legacy
  timestamp?: Date
  formattedTime?: string
  type: 'cycle' | 'reasoning' | 'trade' | 'price' | 'human'
  message: string
}

interface ActivityStreamProps {
  events: ActivityEvent[]
}

export function ActivityStream({ events }: ActivityStreamProps) {
  const getEventStyle = (type: ActivityEvent['type']) => {
    switch (type) {
      case 'cycle':
        return 'text-foreground font-medium'
      case 'trade':
        return 'text-green-500'
      case 'reasoning':
        return 'text-muted-foreground'
      case 'price':
        return 'text-muted-foreground'
      case 'human':
        return 'text-blue-400'
      default:
        return 'text-foreground'
    }
  }

  const getCycleMarker = (type: ActivityEvent['type']) => {
    if (type === 'cycle') {
      return <span className="text-amber-500 mr-1">●</span>
    }
    if (type === 'trade') {
      return <span className="text-green-500 mr-1">●</span>
    }
    if (type === 'human') {
      return <span className="text-blue-400 mr-1">●</span>
    }
    return null
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-4 py-2 border-b border-border">
        <span className="text-xs uppercase tracking-widest text-muted-foreground">Live</span>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-1.5">
          {events.map((event) => (
            <div key={event.id} className="flex items-start gap-3 font-mono text-sm">
              <span className="text-muted-foreground shrink-0 w-12">{event.time ?? event.formattedTime ?? '--:--'}</span>
              <span className={getEventStyle(event.type)}>
                {getCycleMarker(event.type)}
                {event.message}
              </span>
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
