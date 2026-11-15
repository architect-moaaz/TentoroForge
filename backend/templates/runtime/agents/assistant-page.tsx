import { ChatWidget } from "@/components/agents/ChatWidget";

/** The agent as a page of its own — /assistant. Forge runtime — do not remove. */
export default function AssistantPage() {
  return (
    <div className="mx-auto h-[calc(100vh-8rem)] max-w-3xl">
      <ChatWidget variant="page" />
    </div>
  );
}
