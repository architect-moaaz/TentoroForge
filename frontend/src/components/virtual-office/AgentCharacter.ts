// ── Agent Character State Machine ───────────────────────────────────────────

import type {
  AgentInfo,
  AgentCharacterState,
  AgentVisualState,
  DeskPosition,
  Direction,
  Position,
} from "./types";
import {
  getIdleFrame,
  getWalkFrame,
  getWorkFrame,
  getBobOffset,
  getDirectionFromMovement,
} from "./utils/animation";

const WALK_SPEED = 3; // tiles per second

export class AgentCharacter {
  private agentInfo: AgentInfo;
  private desk: DeskPosition;
  private _state: AgentVisualState = "idle";
  private position: Position;
  private direction: Direction;
  private path: Position[] = [];
  private pathIndex = 0;
  private targetPosition: Position | undefined;
  private speechBubble: string | undefined;
  private speechBubbleType: "normal" | "error" | "success" = "normal";
  private progress: number | undefined;
  private node: string | undefined;
  private tally: { done: number; total: number } | undefined;
  private attempt: { n: number; of: number } | undefined;
  private animFrame = 0;
  private walkProgress = 0; // fractional progress between current and next path node
  private onArrivalCallback: (() => void) | undefined;

  constructor(agentInfo: AgentInfo, desk: DeskPosition) {
    this.agentInfo = agentInfo;
    this.desk = desk;
    this.position = { x: desk.x, y: desk.y };
    this.direction = desk.facing;
  }

  // ── Public methods ─────────────────────────────────────────────────────

  /**
   * Advance the character's state each frame.
   * @param dt delta time in seconds
   * @param timestamp performance.now() value for animation
   */
  update(dt: number, timestamp: number): void {
    switch (this._state) {
      case "walking":
        this.advanceWalk(dt);
        this.animFrame = getWalkFrame(timestamp);
        break;
      case "working":
        this.animFrame = getWorkFrame(timestamp);
        break;
      case "reading":
        this.animFrame = getWorkFrame(timestamp);
        break;
      case "idle":
      case "waiting":
        this.animFrame = getIdleFrame(timestamp);
        // Apply bob offset via animFrame; renderer can use getBobOffset
        break;
      case "celebrating":
        this.animFrame = getWalkFrame(timestamp); // reuse walk cycle for celebration
        break;
      case "error":
        this.animFrame = getIdleFrame(timestamp);
        break;
      case "handoff":
        this.animFrame = getIdleFrame(timestamp);
        break;
      case "protesting":
        this.animFrame = getWalkFrame(timestamp);
        break;
      case "retrying":
        // Still at the desk and still working — just having a worse time of
        // it. Reusing the work cycle keeps the retry legible as *the same
        // job again* rather than a different activity.
        this.animFrame = getWorkFrame(timestamp);
        break;
      case "blocked":
      case "skipped":
        this.animFrame = getIdleFrame(timestamp);
        break;
    }
  }

  /**
   * Start walking along a path to a target.
   */
  moveTo(target: Position, path: Position[]): void {
    if (path.length < 2) {
      // Already at target — snap position and fire arrival callback immediately
      this.position = target;
      if (this.onArrivalCallback) {
        const cb = this.onArrivalCallback;
        this.onArrivalCallback = undefined;
        cb();
      }
      return;
    }
    this._state = "walking";
    this.path = path;
    this.pathIndex = 0;
    this.walkProgress = 0;
    this.targetPosition = target;
    this.speechBubble = undefined;
  }

  /**
   * Switch to working state with optional speech bubble.
   */
  startWorking(message?: string): void {
    this._state = "working";
    this.path = [];
    this.targetPosition = undefined;
    this.attempt = undefined;
    if (message) {
      this.speechBubble = message;
      this.speechBubbleType = "normal";
    }
  }

  /**
   * Switch to reading state with optional speech bubble.
   */
  startReading(message?: string): void {
    this._state = "reading";
    this.path = [];
    this.targetPosition = undefined;
    if (message) {
      this.speechBubble = message;
      this.speechBubbleType = "normal";
    }
  }

  /**
   * Show error state with a message.
   */
  showError(message: string): void {
    this._state = "error";
    this.path = [];
    this.targetPosition = undefined;
    this.speechBubble = message;
    this.speechBubbleType = "error";
  }

  /**
   * Celebration state.
   */
  celebrate(): void {
    this._state = "celebrating";
    this.path = [];
    this.targetPosition = undefined;
    this.speechBubble = undefined;
    this.speechBubbleType = "success";
  }

  /**
   * Protest state — agents are angry about credits running out.
   */
  protest(message: string): void {
    this._state = "protesting";
    this.path = [];
    this.targetPosition = undefined;
    this.speechBubble = message;
    this.speechBubbleType = "error";
  }

  /**
   * A proposal was refused and the same call is going round again (§103).
   */
  retry(attempt: number, of: number, reason?: string): void {
    this._state = "retrying";
    this.path = [];
    this.targetPosition = undefined;
    this.attempt = { n: attempt, of };
    if (reason) {
      this.speechBubble = reason;
      this.speechBubbleType = "error";
    }
  }

  /**
   * The agent cannot proceed — it asked a question, or nothing here can do
   * the job. Distinct from `error`: nothing went wrong, the work is parked.
   */
  block(reason?: string): void {
    this._state = "blocked";
    this.path = [];
    this.targetPosition = undefined;
    this.progress = undefined;
    this.tally = undefined;
    this.attempt = undefined;
    if (reason) {
      this.speechBubble = reason;
      this.speechBubbleType = "normal";
    }
  }

  /**
   * The node never ran because its inputs never arrived. The agent shrugs.
   */
  skip(reason?: string): void {
    this._state = "skipped";
    this.path = [];
    this.targetPosition = undefined;
    this.progress = undefined;
    this.tally = undefined;
    this.attempt = undefined;
    if (reason) {
      this.speechBubble = reason;
      this.speechBubbleType = "normal";
    }
  }

  /** The DAG node this agent is currently running. */
  setNode(node: string | undefined): void {
    this.node = node;
  }

  /** Fan-out position, while authoring one artifact per subject. */
  setTally(done: number, total: number): void {
    this.tally = total > 1 ? { done, total } : undefined;
  }

  /**
   * Set speech bubble text and type.
   */
  setSpeechBubble(text: string, type: "normal" | "error" | "success" = "normal"): void {
    this.speechBubble = text;
    this.speechBubbleType = type;
  }

  /**
   * Alias for setIdle (compatibility).
   */
  goIdle(): void {
    this.setIdle();
  }

  /**
   * Alias for showError (compatibility).
   */
  setError(message: string): void {
    this.showError(message);
  }

  /**
   * Return to idle state.
   */
  setIdle(): void {
    this._state = "idle";
    this.path = [];
    this.targetPosition = undefined;
    this.speechBubble = undefined;
    this.speechBubbleType = "normal";
    this.progress = undefined;
    this.node = undefined;
    this.tally = undefined;
    this.attempt = undefined;
  }

  /**
   * Walk back to the agent's assigned desk.
   * The caller is responsible for computing the path via the pathfinder and
   * calling moveTo(). This is a convenience that sets up the callback.
   */
  walkToDesk(): void {
    // This is a high-level intent; the orchestrator should compute the path
    // and call moveTo(). We record the target so getState() exposes it.
    this.targetPosition = { x: this.desk.x, y: this.desk.y };
  }

  /**
   * Set a callback invoked when the agent arrives at its walk target.
   */
  set onArrival(cb: (() => void) | undefined) {
    this.onArrivalCallback = cb;
  }

  /**
   * Set progress percentage (0-1) for working state.
   */
  setProgress(p: number): void {
    this.progress = p;
  }

  /**
   * Get the current renderable state snapshot.
   */
  getState(): AgentCharacterState {
    return {
      id: this.agentInfo.id,
      name: this.agentInfo.name,
      spriteKey: this.agentInfo.spriteKey,
      room: this.agentInfo.room,
      state: this._state,
      position: { ...this.position },
      targetPosition: this.targetPosition ? { ...this.targetPosition } : undefined,
      path: this.path.length > 0 ? [...this.path] : undefined,
      direction: this.direction,
      speechBubble: this.speechBubble,
      speechBubbleType: this.speechBubbleType,
      progress: this.progress,
      animFrame: this.animFrame,
      onArrival: this.onArrivalCallback,
      node: this.node,
      tally: this.tally ? { ...this.tally } : undefined,
      attempt: this.attempt ? { ...this.attempt } : undefined,
    };
  }

  // ── Private ────────────────────────────────────────────────────────────

  private advanceWalk(dt: number): void {
    if (this.path.length === 0 || this.pathIndex >= this.path.length - 1) {
      this.arriveAtTarget();
      return;
    }

    const from = this.path[this.pathIndex];
    const to = this.path[this.pathIndex + 1];

    // Update facing direction
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    if (dx !== 0 || dy !== 0) {
      this.direction = getDirectionFromMovement(dx, dy);
    }

    // Advance progress along this segment
    this.walkProgress += WALK_SPEED * dt;

    while (this.walkProgress >= 1 && this.pathIndex < this.path.length - 1) {
      this.walkProgress -= 1;
      this.pathIndex++;

      if (this.pathIndex >= this.path.length - 1) {
        // Arrived at final node
        this.position = { ...this.path[this.path.length - 1] };
        this.arriveAtTarget();
        return;
      }
    }

    // Interpolate position between current and next path node
    if (this.pathIndex < this.path.length - 1) {
      const a = this.path[this.pathIndex];
      const b = this.path[this.pathIndex + 1];
      const t = Math.min(this.walkProgress, 1);
      this.position = {
        x: a.x + (b.x - a.x) * t,
        y: a.y + (b.y - a.y) * t,
      };

      // Update direction for interpolated segment
      const sdx = b.x - a.x;
      const sdy = b.y - a.y;
      if (sdx !== 0 || sdy !== 0) {
        this.direction = getDirectionFromMovement(sdx, sdy);
      }
    }
  }

  private arriveAtTarget(): void {
    this._state = "idle";
    this.path = [];
    this.walkProgress = 0;
    this.pathIndex = 0;
    if (this.targetPosition) {
      this.position = { ...this.targetPosition };
    }
    this.targetPosition = undefined;

    if (this.onArrivalCallback) {
      const cb = this.onArrivalCallback;
      this.onArrivalCallback = undefined;
      cb();
    }
  }
}
