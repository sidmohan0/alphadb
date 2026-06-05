import { Skill } from "./types"

export const skillRegistry: Skill[] = [
  // Strategies
  {
    id: "list_strategies",
    name: "List Strategies",
    description: "Get all strategies with current status",
    category: "strategies",
    params: [
      { name: "status", type: "enum", required: false, description: "Filter by status", enumValues: ["running", "paused", "stopped", "all"] }
    ],
    triggers: {
      commands: ["list", "show", "strategies"],
      naturalLanguage: ["list strategies", "show strategies", "what strategies", "my strategies"]
    },
    returns: "data"
  },
  {
    id: "pause_strategy",
    name: "Pause Strategy",
    description: "Pause a running strategy",
    category: "strategies",
    params: [
      { name: "id", type: "strategy_id", required: true, description: "Strategy ID to pause" }
    ],
    triggers: {
      commands: ["pause"],
      naturalLanguage: ["pause", "hold", "freeze"]
    },
    returns: "confirmation"
  },
  {
    id: "resume_strategy",
    name: "Resume Strategy",
    description: "Resume a paused strategy",
    category: "strategies",
    params: [
      { name: "id", type: "strategy_id", required: true, description: "Strategy ID to resume" }
    ],
    triggers: {
      commands: ["resume", "start", "unpause"],
      naturalLanguage: ["resume", "start", "continue", "unpause"]
    },
    returns: "confirmation"
  },
  {
    id: "stop_strategy",
    name: "Stop Strategy",
    description: "Fully stop a strategy and close positions",
    category: "strategies",
    params: [
      { name: "id", type: "strategy_id", required: true, description: "Strategy ID to stop" }
    ],
    triggers: {
      commands: ["stop", "kill", "halt"],
      naturalLanguage: ["stop", "kill", "halt", "terminate"]
    },
    returns: "confirmation",
    requiresConfirmation: true
  },
  {
    id: "pause_all",
    name: "Pause All Strategies",
    description: "Pause all running strategies",
    category: "strategies",
    params: [],
    triggers: {
      commands: ["pause all"],
      naturalLanguage: ["pause all", "pause everything", "hold all"]
    },
    returns: "confirmation"
  },
  {
    id: "pause_losing",
    name: "Pause Losing Strategies",
    description: "Pause all strategies with negative P&L today",
    category: "strategies",
    params: [],
    triggers: {
      commands: ["pause losing"],
      naturalLanguage: ["pause losing", "pause negative", "stop the losers", "pause strategies with negative"]
    },
    returns: "confirmation"
  },

  // Positions
  {
    id: "get_positions",
    name: "Get Positions",
    description: "Get current positions across all strategies",
    category: "positions",
    params: [
      { name: "strategy_id", type: "strategy_id", required: false, description: "Filter by strategy" }
    ],
    triggers: {
      commands: ["positions", "pos"],
      naturalLanguage: ["positions", "what am i holding", "current positions", "show positions"]
    },
    returns: "data"
  },
  {
    id: "get_pnl",
    name: "Get P&L",
    description: "Get profit and loss summary",
    category: "positions",
    params: [
      { name: "period", type: "enum", required: false, description: "Time period", enumValues: ["today", "session", "week", "all"] }
    ],
    triggers: {
      commands: ["pnl", "profit"],
      naturalLanguage: ["pnl", "profit", "how much", "making money", "performance"]
    },
    returns: "data"
  },

  // Integrations
  {
    id: "open_discord",
    name: "Open Discord",
    description: "Open Discord channel",
    category: "integrations",
    params: [
      { name: "channel", type: "string", required: false, description: "Channel name" }
    ],
    triggers: {
      commands: ["discord"],
      naturalLanguage: ["open discord", "discord"]
    },
    returns: "confirmation"
  },
  {
    id: "send_notification",
    name: "Send Notification",
    description: "Send a notification via configured channels",
    category: "integrations",
    params: [
      { name: "message", type: "string", required: true, description: "Message to send" },
      { name: "channel", type: "enum", required: false, description: "Notification channel", enumValues: ["slack", "discord", "email"] }
    ],
    triggers: {
      commands: ["notify", "alert"],
      naturalLanguage: ["notify", "alert", "send", "message"]
    },
    returns: "confirmation"
  },

  // System
  {
    id: "get_status",
    name: "Get Status",
    description: "Get system status and health",
    category: "system",
    params: [],
    triggers: {
      commands: ["status", "health"],
      naturalLanguage: ["status", "health", "how are things", "system status"]
    },
    returns: "data"
  },
  {
    id: "help",
    name: "Help",
    description: "Show available commands and skills",
    category: "system",
    params: [],
    triggers: {
      commands: ["help", "?", "commands"],
      naturalLanguage: ["help", "what can you do", "commands", "how do i"]
    },
    returns: "data"
  }
]

export function findSkillByInput(input: string): Skill | null {
  const normalizedInput = input.toLowerCase().trim()
  
  // Exact match first (highest priority)
  for (const skill of skillRegistry) {
    for (const command of skill.triggers.commands) {
      if (normalizedInput === command) {
        return skill
      }
    }
  }
  
  // Check for "show pnl" specifically before "show" alone
  if (normalizedInput.includes("pnl") || normalizedInput.includes("profit") || normalizedInput.includes("p&l")) {
    return skillRegistry.find(s => s.id === "get_pnl") || null
  }
  
  // Check exact command prefix matches
  for (const skill of skillRegistry) {
    for (const command of skill.triggers.commands) {
      if (normalizedInput.startsWith(command + " ") || normalizedInput === command) {
        return skill
      }
    }
  }
  
  // Then check natural language triggers
  for (const skill of skillRegistry) {
    for (const phrase of skill.triggers.naturalLanguage) {
      if (normalizedInput.includes(phrase)) {
        return skill
      }
    }
  }
  
  return null
}

export function getSkillsByCategory(category: string): Skill[] {
  return skillRegistry.filter(s => s.category === category)
}
