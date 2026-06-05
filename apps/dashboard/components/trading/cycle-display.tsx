'use client'

interface CycleDisplayProps {
  secondsRemaining: number
  position: {
    side: 'ABOVE' | 'BELOW' | null
    price: number | null
    contracts: number
  }
  assessment: {
    action: string
    confidence: number
  }
}

export function CycleDisplay({ secondsRemaining, position, assessment }: CycleDisplayProps) {
  const minutes = Math.floor(secondsRemaining / 60)
  const seconds = secondsRemaining % 60
  const timeDisplay = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`

  return (
    <div className="flex flex-col items-center justify-center py-12 border-b border-border">
      <div className="text-sm uppercase tracking-widest text-muted-foreground mb-2">
        Next cycle in
      </div>
      <div className="font-mono text-6xl font-bold text-foreground tracking-tight">
        {timeDisplay}
      </div>
      
      <div className="mt-8 flex flex-col items-center gap-2">
        {position.side ? (
          <div className="text-lg text-foreground">
            Current Position:{' '}
            <span className={position.side === 'ABOVE' ? 'text-green-500' : 'text-red-500'}>
              {position.side}
            </span>
            {' @ '}
            <span className="font-mono">{position.price?.toFixed(2)}</span>
            <span className="text-muted-foreground ml-2">
              ({position.contracts} contracts)
            </span>
          </div>
        ) : (
          <div className="text-lg text-muted-foreground">No position</div>
        )}
        
        <div className="text-sm text-muted-foreground">
          Agent Assessment:{' '}
          <span className="text-foreground">{assessment.action}</span>
          {' — '}
          <span className="font-mono">confidence {assessment.confidence.toFixed(2)}</span>
        </div>
      </div>
    </div>
  )
}
