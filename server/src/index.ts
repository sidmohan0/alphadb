import cors from "cors";
import express from "express";

const app = express();
const PORT = Number(process.env.PORT ?? 4000);

app.use(cors());
app.use(express.json());

const messages: { id: number; message: string }[] = [
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

app.listen(PORT, () => {
  console.log(`🚀 Server running on http://localhost:${PORT}`);
});
