import { redirect } from "next/navigation";

// The home page moves in ADR-0008 P3-4; until then the chat is the start page.
export default function Home() {
  redirect("/chat");
}
