interface SessionStatsProps {
  sessionPnL: number
  todayPnL: number
  winRate: number
}

export function SessionStats({ sessionPnL, todayPnL, winRate }: SessionStatsProps) {
  const formatPnL = (value: number) => {
    const prefix = value >= 0 ? '+' : ''
    return `${prefix}$${Math.abs(value).toFixed(2)}`
  }

  const getPnLColor = (value: number) => {
    if (value > 0) return 'text-green-500'
    if (value < 0) return 'text-red-500'
    return 'text-muted-foreground'
  }

  return (
    <footer className="flex items-center justify-center gap-8 px-4 py-3 bg-card border-t border-border">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Session:</span>
        <span className={`font-mono font-medium ${getPnLColor(sessionPnL)}`}>
          {formatPnL(sessionPnL)}
        </span>
      </div>
      
      <div className="h-4 w-px bg-border" />
      
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Today:</span>
        <span className={`font-mono font-medium ${getPnLColor(todayPnL)}`}>
          {formatPnL(todayPnL)}
        </span>
      </div>
      
      <div className="h-4 w-px bg-border" />
      
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Win rate:</span>
        <span className="font-mono font-medium text-foreground">
          {Math.round(winRate * 100)}%
        </span>
      </div>
    </footer>
  )
}
