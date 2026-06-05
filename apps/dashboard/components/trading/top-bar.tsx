'use client'

import { useState } from 'react'
import { Octagon } from 'lucide-react'

interface TopBarProps {
  btcPrice: number
  threshold: number
  currentTime: string
  onKill: () => void
}

export function TopBar({ btcPrice, threshold, currentTime, onKill }: TopBarProps) {
  const [isKilling, setIsKilling] = useState(false)

  const handleKill = () => {
    setIsKilling(true)
    onKill()
  }

  const formatPrice = (price: number) => {
    return price.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 })
  }

  return (
    <header className="flex items-center justify-between px-4 py-2 bg-card border-b border-border">
      <div className="flex items-center gap-4">
        <button
          onClick={handleKill}
          disabled={isKilling}
          className="flex items-center gap-2 px-4 py-2 bg-destructive text-destructive-foreground font-semibold text-sm rounded hover:bg-destructive/90 transition-colors disabled:opacity-50"
        >
          <Octagon className="h-4 w-4" />
          {isKilling ? 'STOPPING...' : 'KILL'}
        </button>
        
        <div className="h-6 w-px bg-border" />
        
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">BTC</span>
          <span className="font-mono font-semibold text-foreground">{formatPrice(btcPrice)}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Above/Below</span>
        <span className="font-mono font-semibold text-foreground">{formatPrice(threshold)}</span>
      </div>

      <div className="font-mono text-sm text-muted-foreground">
        {currentTime}
      </div>
    </header>
  )
}
