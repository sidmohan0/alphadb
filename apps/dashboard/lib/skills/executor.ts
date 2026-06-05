import { apiPost } from "@/lib/alphadb-api"
import { SkillResult } from "./types"

interface AskResponse {
  skill: string
  messages: Array<{ role: string; content: string }>
  result: unknown
}

export async function executeSkill(input: string): Promise<{
  skill: string | null
  result: SkillResult
}> {
  try {
    const data = await apiPost<AskResponse>("/ask", { message: input })
    return {
      skill: data.skill || null,
      result: {
        success: true,
        message: data.messages.map((message) => message.content).join("\n"),
        data: data.result,
        suggestions: nextSuggestions(data.skill),
      },
    }
  } catch (err) {
    return {
      skill: null,
      result: {
        success: false,
        message: err instanceof Error ? err.message : "Agent request failed",
        suggestions: ["status", "list strategies", "show data views"],
      },
    }
  }
}

function nextSuggestions(skill: string) {
  if (skill.startsWith("data.")) return ["list datasets", "status", "lab insights"]
  if (skill.startsWith("lab.")) return ["lab entries", "lab insights", "status"]
  if (skill.startsWith("strategy.")) return ["list strategies", "compile strategy brief", "status"]
  return ["status", "list strategies", "show data views"]
}
