'use client'

import { ReactNode } from 'react'

interface DashboardShellProps {
  sidebar: ReactNode
  topBar: ReactNode
  workspaceHeader: ReactNode
  main: ReactNode
  inspector: ReactNode
}

export function DashboardShell({
  sidebar,
  topBar,
  workspaceHeader,
  main,
  inspector,
}: DashboardShellProps) {
  return (
    <div className="grid h-screen grid-cols-[auto_1fr_auto] grid-rows-[auto_1fr] overflow-hidden bg-background">
      {/* Top Bar - spans all columns */}
      <div className="col-span-3 col-start-1 row-start-1">
        {topBar}
      </div>

      {/* Sidebar - spans row 2 */}
      <div className="col-start-1 row-start-2 overflow-hidden">
        {sidebar}
      </div>

      {/* Main workspace area - center column, row 2 */}
      <div className="col-start-2 row-start-2 flex flex-col overflow-hidden">
        {workspaceHeader}
        {main}
      </div>

      {/* Inspector panel - right column, row 2 */}
      <div className="col-start-3 row-start-2 overflow-hidden">
        {inspector}
      </div>
    </div>
  )
}
