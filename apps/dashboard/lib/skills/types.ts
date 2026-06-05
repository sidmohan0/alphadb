export type SkillCategory = 
  | "strategies" 
  | "positions" 
  | "research" 
  | "integrations" 
  | "system"

export type SkillReturnType = "void" | "data" | "confirmation"

export interface SkillParam {
  name: string
  type: "string" | "number" | "boolean" | "strategy_id" | "enum"
  required: boolean
  description: string
  enumValues?: string[]
}

export interface Skill {
  id: string
  name: string
  description: string
  category: SkillCategory
  params: SkillParam[]
  triggers: {
    commands: string[]
    naturalLanguage: string[]
  }
  returns: SkillReturnType
  requiresConfirmation?: boolean
}

export interface SkillInvocation {
  skillId: string
  params: Record<string, unknown>
}

export interface SkillResult {
  success: boolean
  message: string
  data?: unknown
  suggestions?: string[]
}

export type MessageType = 
  | "human" 
  | "agent" 
  | "action" 
  | "error" 
  | "suggestion" 
  | "skill"

export interface TerminalMessage {
  id: string
  type: MessageType
  content: string
  timestamp: Date
  formattedTime: string
  skillId?: string
  data?: unknown
}

export type AgentStatus = "idle" | "thinking" | "acting" | "error" | "disconnected"
