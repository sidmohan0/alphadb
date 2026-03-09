import { randomUUID } from "crypto";
import { Router } from "express";

import { authStatusForRequest } from "./authService";

const router = Router();

function toSingleString(value: unknown): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length ? trimmed : undefined;
  }

  if (Array.isArray(value) && value.length > 0 && typeof value[0] === "string") {
    const trimmed = value[0].trim();
    return trimmed.length ? trimmed : undefined;
  }

  return undefined;
}

router.get("/me", (req, res) => {
  const requestId = toSingleString(req.header("x-request-id")) || randomUUID();

  try {
    const auth = authStatusForRequest(req);
    res.json({ ...auth, requestId });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unauthorized";
    res.status(401).json({
      error: "Unauthorized",
      code: "unauthorized",
      message,
      retryable: false,
      requestId,
    });
  }
});

export const authRouter = router;
