import { SignInButton, UserButton } from "@clerk/nextjs";
import { currentUser } from "@clerk/nextjs/server";
import { mySessions, upsertUser } from "@/lib/db";
import { LiveNow } from "./live";
import { OpenLab } from "./open-lab";
import { MySessions } from "./my-sessions";

export const dynamic = "force-dynamic";

export default async function Home() {
  const user = await currentUser();
  if (user) {
    await upsertUser({
      id: user.id,
      email: user.primaryEmailAddress?.emailAddress ?? "",
      name: [user.firstName, user.lastName].filter(Boolean).join(" "),
    });
  }
  const sessions = user ? await mySessions(user.id).catch(() => []) : [];
  return (
    <main>
      <div className="top">
        <h1>MuJoCo Playground</h1>
        {user && <UserButton />}
      </div>
      <p className="sub">Build a robot lab, give an AI model a task, and watch it work.</p>

      <div className="card">
        {user ? (
          <>
            <p className="status">Signed in as {user.primaryEmailAddress?.emailAddress}</p>
            <p className="small" style={{ margin: "8px 0 14px" }}>Your own lab, just for you. It takes about half a minute to start.</p>
            <OpenLab />
          </>
        ) : (
          <>
            <p className="status">Sign in to get your own lab</p>
            <p className="small" style={{ margin: "8px 0 14px" }}>Your sessions are saved to your account, so you can come back to them.</p>
            <SignInButton mode="modal"><button className="primary">Sign in with Google</button></SignInButton>
          </>
        )}
      </div>

      {user && (
        <div className="card">
          <h2>My sessions</h2>
          <MySessions initial={sessions} />
        </div>
      )}

      <div className="card">
        <h2>Live now</h2>
        <LiveNow />
      </div>

      <div className="links small">
        {user && <a href="/runs">Your runs: tasks, outcomes and the code the AI wrote</a>}
      </div>
    </main>
  );
}
