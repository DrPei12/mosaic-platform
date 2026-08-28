import { ChatWorkspace } from "@/features/chat/chat-workspace";
import { requireServerSession } from "@/features/auth/server-session";

export default async function ChatPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  await requireServerSession(`/chat/${encodeURIComponent(conversationId)}`);
  return <ChatWorkspace conversationId={conversationId} />;
}
