'use client'

import {
  Activity,
  BarChart3,
  Beaker,
  Box,
  Database,
  FileCode,
  FlaskConical,
  Layers,
  Play,
  Settings,
  Shield,
  TrendingUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navGroups = [
  {
    items: [
      { icon: Activity, label: 'Live Ops', active: true },
      { icon: Play, label: 'Strategy Runner' },
      { icon: Shield, label: 'Risk' },
    ],
  },
  {
    items: [
      { icon: Beaker, label: 'Research' },
      { icon: BarChart3, label: 'Backtests' },
      { icon: FlaskConical, label: 'Experiments' },
    ],
  },
  {
    items: [
      { icon: Box, label: 'Model Registry' },
      { icon: Database, label: 'Data' },
      { icon: Layers, label: 'Markets' },
    ],
  },
  {
    items: [
      { icon: TrendingUp, label: 'Positions' },
      { icon: FileCode, label: 'Settlement' },
    ],
  },
]

interface SidebarProps {
  activeItem?: string
  onItemClick?: (label: string) => void
}

export function Sidebar({ activeItem = 'Live Ops', onItemClick }: SidebarProps) {
  return (
    <aside className="flex h-full w-[200px] flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex h-12 items-center gap-2 border-b border-sidebar-border px-4">
        <div className="flex h-6 w-6 items-center justify-center rounded bg-success text-success-foreground">
          <span className="text-xs font-bold">α</span>
        </div>
        <span className="text-sm font-semibold text-sidebar-foreground">AlphaDB</span>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {navGroups.map((group, groupIdx) => (
          <div key={groupIdx} className="mb-1">
            {group.items.map((item) => {
              const isActive = item.label === activeItem
              return (
                <button
                  key={item.label}
                  onClick={() => onItemClick?.(item.label)}
                  className={cn(
                    'flex w-full items-center gap-2.5 px-4 py-1.5 text-left text-xs transition-colors',
                    isActive
                      ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                      : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'
                  )}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  <span>{item.label}</span>
                </button>
              )
            })}
            {groupIdx < navGroups.length - 1 && (
              <div className="mx-4 my-2 border-t border-sidebar-border" />
            )}
          </div>
        ))}
      </nav>

      <div className="border-t border-sidebar-border p-2">
        <button className="flex w-full items-center gap-2.5 px-2 py-1.5 text-xs text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground">
          <Settings className="h-3.5 w-3.5" />
          <span>Settings</span>
        </button>
      </div>
    </aside>
  )
}
