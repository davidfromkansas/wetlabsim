import { currentUser } from "@clerk/nextjs/server";
import { upsertUser } from "@/lib/db";
import { GoToLab } from "./go-to-lab";
import { StartButton } from "./start-button";

export const dynamic = "force-dynamic";

// Signed in: skip the front page and go straight into your lab (the Playground).
// Signed out: one screen, the headline, a Start button (Google sign-in) and the robot loop.
export default async function Home() {
  const user = await currentUser();
  if (user) {
    await upsertUser({
      id: user.id,
      email: user.primaryEmailAddress?.emailAddress ?? "",
      name: [user.firstName, user.lastName].filter(Boolean).join(" "),
    });
    return <GoToLab />;
  }
  return (
    <div className="land">
      <main className="land-hero">
        <div className="land-copy">
          <h1>Give your agent a robot.</h1>
          <StartButton />
        </div>
        <div className="land-arm">
          {/* The real Franka Panda model from the repo, drawn as a wireframe (see website/arm-wireframe). */}
          <video src="/robot-loop.mp4" poster="/robot-loop.jpg" autoPlay loop muted playsInline preload="auto"
            aria-label="Wireframe of a Franka Panda robot arm putting an apple in a bowl, pouring from a bottle and tidying up on a glowing grid, on a loop" />
        </div>
      </main>
    </div>
  );
}
