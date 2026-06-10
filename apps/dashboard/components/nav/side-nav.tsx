"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Activity, Database, FlaskConical, Layers, SlidersHorizontal, TrendingUp, Zap } from "lucide-react"

const navItems = [
  { href: "/", label: "Live", icon: Activity },
  { href: "/live/config", label: "Config", icon: SlidersHorizontal },
  { href: "/performance", label: "Performance", icon: TrendingUp },
  { href: "/strategies", label: "Strategies", icon: Layers },
  { href: "/data", label: "Data", icon: Database },
  { href: "/lab", label: "Lab", icon: FlaskConical },
]

export function SideNav() {
  const pathname = usePathname()

  return (
    <nav className="w-14 bg-card border-r border-border flex flex-col items-center py-4 gap-1">
      <div className="mb-4 p-2">
        <Zap className="h-5 w-5 text-primary" />
      </div>
      
      {navItems.map((item) => {
        const isActive = pathname === item.href || 
          (item.href !== "/" && pathname.startsWith(item.href))
        
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-md transition-colors",
              isActive
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
            title={item.label}
          >
            <item.icon className="h-5 w-5" />
          </Link>
        )
      })}
    </nav>
  )
}
