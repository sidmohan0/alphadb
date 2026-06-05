import {
  mockStrategy,
  mockOperatingState,
  mockRiskMetrics,
  mockDecisions,
  mockOrders,
  mockEvidenceItems,
  mockDecisionChain,
  mockArtifacts,
  mockSystemHealth,
  mockBacktests,
  mockMarketInstances,
  mockPositionsSummary,
  mockResearchCandidate,
  type Strategy,
  type OperatingState,
  type RiskMetric,
  type Decision,
  type Order,
  type EvidenceItem,
  type DecisionChainStep,
  type Artifact,
  type SystemHealth,
  type Backtest,
  type MarketInstance,
  type PositionsSummary,
  type ResearchCandidate,
} from '@/lib/mock-data'

// This hook serves as a placeholder for future SWR/API integration.
// Currently returns mock data, but can be swapped for real API calls.

export interface DashboardData {
  strategy: Strategy
  operatingState: OperatingState
  riskMetrics: RiskMetric[]
  decisions: Decision[]
  orders: Order[]
  evidenceItems: EvidenceItem[]
  decisionChain: DecisionChainStep[]
  artifacts: Artifact[]
  systemHealth: SystemHealth[]
  backtests: Backtest[]
  marketInstances: MarketInstance[]
  positionsSummary: PositionsSummary
  researchCandidate: ResearchCandidate
  isLoading: boolean
  error: Error | null
}

export function useDashboardData(): DashboardData {
  // In a real implementation, this would use SWR or React Query:
  // const { data, error, isLoading } = useSWR('/api/dashboard', fetcher)

  return {
    strategy: mockStrategy,
    operatingState: mockOperatingState,
    riskMetrics: mockRiskMetrics,
    decisions: mockDecisions,
    orders: mockOrders,
    evidenceItems: mockEvidenceItems,
    decisionChain: mockDecisionChain,
    artifacts: mockArtifacts,
    systemHealth: mockSystemHealth,
    backtests: mockBacktests,
    marketInstances: mockMarketInstances,
    positionsSummary: mockPositionsSummary,
    researchCandidate: mockResearchCandidate,
    isLoading: false,
    error: null,
  }
}
