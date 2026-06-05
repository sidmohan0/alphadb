"use client"

import { useState, useEffect } from "react"
import { 
  Check, 
  AlertCircle, 
  Lightbulb, 
  ExternalLink,
  Database,
  Cloud,
  Coins,
  BarChart3,
  Thermometer,
  Globe,
  ChevronDown,
  ChevronRight,
  Plus,
  Key
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface DataSource {
  id: string
  name: string
  category: "exchange" | "market" | "weather" | "economic" | "social" | "blockchain"
  description: string
  envVar: string
  connected: boolean
  docsUrl?: string
}

interface SuggestedSource {
  source: DataSource
  reason: string
  confidence: "high" | "medium" | "low"
}

// Mock available data sources - in production, this would come from env var detection
const ALL_DATA_SOURCES: DataSource[] = [
  // Exchanges
  { id: "coinbase", name: "Coinbase", category: "exchange", description: "Spot prices, order books, historical trades", envVar: "COINBASE_API_KEY", connected: true, docsUrl: "https://docs.cloud.coinbase.com" },
  { id: "kraken", name: "Kraken", category: "exchange", description: "Spot & futures, funding rates, OHLCV", envVar: "KRAKEN_API_KEY", connected: true, docsUrl: "https://docs.kraken.com" },
  { id: "binance", name: "Binance", category: "exchange", description: "Perpetuals, funding rates, liquidations", envVar: "BINANCE_API_KEY", connected: false, docsUrl: "https://binance-docs.github.io" },
  { id: "bybit", name: "Bybit", category: "exchange", description: "Derivatives, funding, open interest", envVar: "BYBIT_API_KEY", connected: false, docsUrl: "https://bybit-exchange.github.io" },
  
  // Prediction Markets
  { id: "kalshi", name: "Kalshi", category: "market", description: "Event contracts, order books, settlement", envVar: "KALSHI_API_KEY", connected: true, docsUrl: "https://trading-api.readme.io" },
  { id: "polymarket", name: "Polymarket", category: "market", description: "Prediction market odds, liquidity", envVar: "POLYMARKET_API_KEY", connected: false, docsUrl: "https://docs.polymarket.com" },
  
  // Weather
  { id: "noaa", name: "NOAA", category: "weather", description: "Forecasts, historical weather, alerts", envVar: "NOAA_API_KEY", connected: false, docsUrl: "https://www.weather.gov/documentation/services-web-api" },
  { id: "openweather", name: "OpenWeather", category: "weather", description: "Global weather data, forecasts", envVar: "OPENWEATHER_API_KEY", connected: true, docsUrl: "https://openweathermap.org/api" },
  
  // Economic
  { id: "fred", name: "FRED", category: "economic", description: "Federal Reserve economic data", envVar: "FRED_API_KEY", connected: false, docsUrl: "https://fred.stlouisfed.org/docs/api" },
  { id: "bls", name: "BLS", category: "economic", description: "Employment, inflation, CPI data", envVar: "BLS_API_KEY", connected: false, docsUrl: "https://www.bls.gov/developers" },
  
  // Social/Sentiment
  { id: "twitter", name: "X/Twitter", category: "social", description: "Social sentiment, trending topics", envVar: "TWITTER_API_KEY", connected: false, docsUrl: "https://developer.twitter.com" },
  { id: "reddit", name: "Reddit", category: "social", description: "Subreddit sentiment, mentions", envVar: "REDDIT_API_KEY", connected: false, docsUrl: "https://www.reddit.com/dev/api" },
  
  // Blockchain
  { id: "glassnode", name: "Glassnode", category: "blockchain", description: "On-chain metrics, whale movements", envVar: "GLASSNODE_API_KEY", connected: false, docsUrl: "https://docs.glassnode.com" },
  { id: "dune", name: "Dune Analytics", category: "blockchain", description: "Custom on-chain queries", envVar: "DUNE_API_KEY", connected: false, docsUrl: "https://dune.com/docs/api" },
]

// Keywords that suggest specific data sources
const KEYWORD_MAPPINGS: Record<string, string[]> = {
  // Crypto price sources
  "btc": ["coinbase", "kraken", "binance", "bybit", "glassnode"],
  "bitcoin": ["coinbase", "kraken", "binance", "bybit", "glassnode"],
  "eth": ["coinbase", "kraken", "binance", "bybit", "glassnode"],
  "ethereum": ["coinbase", "kraken", "binance", "bybit", "glassnode"],
  "crypto": ["coinbase", "kraken", "binance", "bybit"],
  "price": ["coinbase", "kraken", "binance"],
  
  // Derivatives
  "funding": ["binance", "bybit", "kraken"],
  "perpetual": ["binance", "bybit"],
  "futures": ["binance", "bybit", "kraken"],
  "liquidation": ["binance", "bybit"],
  "open interest": ["binance", "bybit"],
  
  // On-chain
  "whale": ["glassnode", "dune"],
  "on-chain": ["glassnode", "dune"],
  "wallet": ["glassnode", "dune"],
  "chain": ["glassnode", "dune"],
  
  // Weather
  "weather": ["noaa", "openweather"],
  "temperature": ["noaa", "openweather"],
  "storm": ["noaa", "openweather"],
  "hurricane": ["noaa"],
  "forecast": ["noaa", "openweather"],
  
  // Economic
  "inflation": ["fred", "bls"],
  "cpi": ["bls", "fred"],
  "employment": ["bls", "fred"],
  "jobs": ["bls", "fred"],
  "fed": ["fred"],
  "interest rate": ["fred"],
  "gdp": ["fred"],
  
  // Social
  "sentiment": ["twitter", "reddit"],
  "twitter": ["twitter"],
  "reddit": ["reddit"],
  "social": ["twitter", "reddit"],
  "trending": ["twitter", "reddit"],
  
  // Prediction markets
  "election": ["kalshi", "polymarket"],
  "event": ["kalshi", "polymarket"],
  "prediction": ["kalshi", "polymarket"],
}

function parseIdeaForSuggestions(ideaText: string): SuggestedSource[] {
  if (!ideaText.trim()) return []
  
  const lowerText = ideaText.toLowerCase()
  const suggestedIds = new Map<string, { count: number; reasons: string[] }>()
  
  // Check each keyword
  for (const [keyword, sourceIds] of Object.entries(KEYWORD_MAPPINGS)) {
    if (lowerText.includes(keyword)) {
      for (const sourceId of sourceIds) {
        const existing = suggestedIds.get(sourceId) || { count: 0, reasons: [] }
        existing.count++
        if (!existing.reasons.includes(keyword)) {
          existing.reasons.push(keyword)
        }
        suggestedIds.set(sourceId, existing)
      }
    }
  }
  
  // Convert to SuggestedSource array
  const suggestions: SuggestedSource[] = []
  for (const [sourceId, { count, reasons }] of suggestedIds) {
    const source = ALL_DATA_SOURCES.find(s => s.id === sourceId)
    if (source && !source.connected) { // Only suggest unconnected sources
      suggestions.push({
        source,
        reason: `Mentioned: ${reasons.slice(0, 3).join(", ")}`,
        confidence: count >= 3 ? "high" : count >= 2 ? "medium" : "low"
      })
    }
  }
  
  // Sort by confidence
  return suggestions.sort((a, b) => {
    const order = { high: 0, medium: 1, low: 2 }
    return order[a.confidence] - order[b.confidence]
  }).slice(0, 5) // Max 5 suggestions
}

const categoryIcons: Record<string, React.ReactNode> = {
  exchange: <Coins className="h-3.5 w-3.5" />,
  market: <BarChart3 className="h-3.5 w-3.5" />,
  weather: <Thermometer className="h-3.5 w-3.5" />,
  economic: <Globe className="h-3.5 w-3.5" />,
  social: <Cloud className="h-3.5 w-3.5" />,
  blockchain: <Database className="h-3.5 w-3.5" />,
}

const categoryLabels: Record<string, string> = {
  exchange: "Exchanges",
  market: "Prediction Markets",
  weather: "Weather",
  economic: "Economic",
  social: "Social",
  blockchain: "Blockchain",
}

interface DataSourcesSectionProps {
  isExpanded: boolean
  onToggle: () => void
  ideaBrief: string
}

export function DataSourcesSection({ isExpanded, onToggle, ideaBrief }: DataSourcesSectionProps) {
  const [suggestions, setSuggestions] = useState<SuggestedSource[]>([])
  
  const connectedSources = ALL_DATA_SOURCES.filter(s => s.connected)
  const connectedByCategory = connectedSources.reduce((acc, source) => {
    if (!acc[source.category]) acc[source.category] = []
    acc[source.category].push(source)
    return acc
  }, {} as Record<string, DataSource[]>)
  
  // Parse idea brief for suggestions
  useEffect(() => {
    const timer = setTimeout(() => {
      setSuggestions(parseIdeaForSuggestions(ideaBrief))
    }, 300) // Debounce
    return () => clearTimeout(timer)
  }, [ideaBrief])
  
  return (
    <div className="border border-border rounded-lg bg-card">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <Database className="h-4 w-4" />
          <span className="font-medium">Data Sources</span>
          <Badge variant="secondary" className="text-xs">
            {connectedSources.length} connected
          </Badge>
          {suggestions.length > 0 && (
            <Badge className="text-xs bg-amber-500/10 text-amber-500 border-amber-500/20">
              {suggestions.length} suggested
            </Badge>
          )}
        </div>
      </button>
      
      {isExpanded && (
        <div className="px-4 pb-4 space-y-6">
          {/* Connected Sources */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Check className="h-3.5 w-3.5 text-emerald-500" />
              Available Sources
            </div>
            
            <div className="grid gap-3">
              {Object.entries(connectedByCategory).map(([category, sources]) => (
                <div key={category} className="space-y-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
                    {categoryIcons[category]}
                    {categoryLabels[category]}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {sources.map(source => (
                      <div
                        key={source.id}
                        className="flex items-center justify-between p-2.5 rounded-md bg-emerald-500/5 border border-emerald-500/20"
                      >
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{source.name}</span>
                            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          </div>
                          <p className="text-xs text-muted-foreground">{source.description}</p>
                        </div>
                        {source.docsUrl && (
                          <a
                            href={source.docsUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1.5 rounded hover:bg-muted transition-colors"
                          >
                            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          
          {/* Suggested Sources */}
          {suggestions.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
                Suggested for this strategy
              </div>
              
              <div className="grid gap-2">
                {suggestions.map(({ source, reason, confidence }) => (
                  <div
                    key={source.id}
                    className="flex items-center justify-between p-2.5 rounded-md bg-amber-500/5 border border-amber-500/20"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-1.5 rounded bg-muted">
                        {categoryIcons[source.category]}
                      </div>
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{source.name}</span>
                          <Badge 
                            variant="outline" 
                            className={cn(
                              "text-[10px] px-1.5",
                              confidence === "high" && "border-amber-500/50 text-amber-500",
                              confidence === "medium" && "border-amber-500/30 text-amber-400",
                              confidence === "low" && "border-muted-foreground/30 text-muted-foreground"
                            )}
                          >
                            {confidence}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">{reason}</p>
                      </div>
                    </div>
                    <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5">
                      <Key className="h-3 w-3" />
                      Connect
                    </Button>
                  </div>
                ))}
              </div>
              
              <p className="text-xs text-muted-foreground">
                <AlertCircle className="h-3 w-3 inline mr-1" />
                Suggestions based on keywords in your Idea Brief. Connect sources in Settings.
              </p>
            </div>
          )}
          
          {/* No suggestions state */}
          {suggestions.length === 0 && ideaBrief.trim() && (
            <div className="text-center py-4 text-sm text-muted-foreground">
              <Lightbulb className="h-4 w-4 mx-auto mb-2 opacity-50" />
              No additional sources suggested based on your idea.
              <br />
              <span className="text-xs">Your connected sources should cover this strategy.</span>
            </div>
          )}
          
          {/* Empty idea state */}
          {!ideaBrief.trim() && (
            <div className="text-center py-4 text-sm text-muted-foreground">
              <Lightbulb className="h-4 w-4 mx-auto mb-2 opacity-50" />
              Add an Idea Brief to get data source suggestions.
            </div>
          )}
          
          {/* Add more sources */}
          <div className="pt-2 border-t border-border">
            <Button variant="ghost" size="sm" className="w-full text-xs text-muted-foreground gap-1.5">
              <Plus className="h-3 w-3" />
              Browse all available data sources
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
