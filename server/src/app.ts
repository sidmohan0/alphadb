import cors from "cors";
import express from "express";

import { polymarketRouter } from "./polymarket/controllers/polymarket.controller";

export type Message = { id: number; message: string };

/**
 * Build the Express app instance for both runtime and testability.
 *
 * Keeping app creation in a factory makes endpoint-level integration tests
 * straightforward without binding to a live server socket.
 */
export function createApp(): express.Express {
  const app = express();

  app.use(cors());
  app.use(express.json());

  const messages: Message[] = [
    { id: 1, message: "Welcome to your TypeScript full-stack boilerplate." },
  ];

  app.get("/api/health", (_req, res) => {
    res.json({ ok: true, service: "server", timestamp: new Date().toISOString() });
  });

  app.get("/api/messages", (_req, res) => {
    res.json(messages);
  });

  app.post("/api/messages", (req, res) => {
    const body = req.body as { message?: string };
    const message = body.message?.trim();

    if (!message) {
      return res.status(400).json({ error: "message is required" });
    }

    const next = { id: messages.length + 1, message };
    messages.push(next);
    res.status(201).json(next);
  });

  app.use("/api/polymarket", polymarketRouter);

  return app;
}
