"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [status, setStatus] = useState("Checking backend...");

  useEffect(() => {
    fetch("http://localhost:8001/health")
      .then((response) => response.json())
      .then((data) => setStatus(`Backend: ${data.status}`))
      .catch(() => setStatus("Backend connection failed"));
  }, []);

  return (
    <main className="p-8">
      <h1 className="text-2xl font-semibold">AI Compassion Coach</h1>
      <p className="mt-4">{status}</p>
    </main>
  );
}