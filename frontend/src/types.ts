export type AgentInfo = {
    id: string;
    name: string;
    description: string;
}

export type ChatMessage = {
    role: "user" | "assistant";
    content: string;
}