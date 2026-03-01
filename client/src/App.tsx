import { useEffect, useState } from "react";

type Health = {
  ok: boolean;
  service: string;
  timestamp: string;
};

type Message = {
  id: number;
  message: string;
};

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [newMessage, setNewMessage] = useState("");
  const [status, setStatus] = useState("Idle");

  useEffect(() => {
    void fetchHealth();
    void fetchMessages();
  }, []);

  const fetchHealth = async () => {
    const res = await fetch("/api/health");
    const data = await res.json();
    setHealth(data);
  };

  const fetchMessages = async () => {
    const res = await fetch("/api/messages");
    const data = await res.json();
    setMessages(data);
  };

  const handleAdd = async () => {
    const trimmed = newMessage.trim();
    if (!trimmed) return;

    setStatus("Posting...");
    const res = await fetch("/api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: trimmed }),
    });

    if (res.ok) {
      setNewMessage("");
      await fetchMessages();
      setStatus("Message added");
    } else {
      const payload = await res.json();
      setStatus(payload.error ?? "Something went wrong");
    }
  };

  return (
    <div className="app">
      <h1>TypeScript Full-Stack Boilerplate</h1>
      <section className="card">
        <h2>Server health</h2>
        {health ? <p>{health.service}: {health.timestamp}</p> : <p>Loading health...</p>}
      </section>

      <section className="card">
        <h2>Messages</h2>
        <ul>
          {messages.map((msg) => (
            <li key={msg.id}>
              <strong>#{msg.id}</strong> {msg.message}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>Add Message</h2>
        <div className="input-row">
          <input
            value={newMessage}
            onChange={(e) => setNewMessage(e.target.value)}
            placeholder="Type a message"
          />
          <button onClick={handleAdd}>Submit</button>
        </div>
        <p>{status}</p>
      </section>

      <button className="ghost" onClick={fetchHealth}>
        Refresh health
      </button>
    </div>
  );
}

export default App;
