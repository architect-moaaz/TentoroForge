"use client";

import { X, Cpu, Users } from "lucide-react";
import { useOfficeStore } from "../OfficeStateManager";
import { AGENT_REGISTRY, DEPARTMENTS, ENGINES } from "../types";

/** The office, explained: every department, who sits in it and what they
 *  do, the engines that stand in it, and how a build moves through them.
 *  Clicking a department looks at it on the floor. */
export function FloorPlanPanel({ onClose }: { onClose: () => void }) {
  const focusRoom = useOfficeStore((s) => s.focusRoom);
  const engines = useOfficeStore((s) => s.engines);
  const activeAgents = useOfficeStore((s) => s.activeAgents);

  return (
    <div className="absolute top-0 left-0 bottom-0 w-[340px] z-20 bg-gray-900/95 backdrop-blur-sm border-r border-gray-700/50 flex flex-col animate-in slide-in-from-left duration-200">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700/50">
        <h3 className="text-sm font-semibold text-white">The office</h3>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-gray-700/50 transition-colors text-gray-400 hover:text-white"
          aria-label="Close the floor plan"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-gray-300">
        <section>
          <h4 className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">How a build moves</h4>
          <p className="text-xs leading-relaxed">
            You talk to <b className="text-white">Smith</b> at the Front Desk. Discovery writes down what the
            app is for; you approve it. Architecture, Data and Design shape the product model; you approve
            that. Then the <b className="text-white">Engineer</b> decides the facts every writer must agree
            on and builds one feature at a time: contracts, processes, rules, statements of what must
            happen, layouts, code — assembled, served on the <b className="text-white">Workbench</b> and
            tried as the people it is for, fixed by Smith where it fails, before the next feature begins.
            What no feature claimed is swept up, the whole application is checked, every statement is tried
            once more, and only then is it handed over. After that, every change you ask for comes back in
            through the Front Desk.
          </p>
        </section>

        {DEPARTMENTS.map((d) => {
          const people = AGENT_REGISTRY.filter((a) => a.room === d.id);
          const machines = ENGINES.filter((e) => e.room === d.id);
          if (!people.length && !machines.length && d.id !== "huddle") return null;
          return (
            <section key={d.id}>
              <button
                onClick={() => focusRoom(d.id)}
                className="w-full text-left flex items-center gap-2 group"
                title="Look at this room"
              >
                <span className="inline-block w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: d.color }} />
                <span className="text-sm font-medium text-white group-hover:underline">{d.label}</span>
              </button>
              <p className="text-[11px] text-gray-400 mt-0.5">{d.description}</p>
              {people.length > 0 && (
                <ul className="mt-1.5 space-y-1">
                  {people.map((a) => (
                    <li key={a.id} className="flex items-start gap-1.5 text-xs">
                      <Users className="w-3 h-3 mt-0.5 shrink-0" style={{ color: a.color }} />
                      <span>
                        <span className={`font-medium ${activeAgents.has(a.id) ? "text-emerald-300" : "text-gray-200"}`}>
                          {a.name}
                        </span>
                        <span className="text-gray-400"> — {a.role}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {machines.length > 0 && (
                <ul className="mt-1.5 space-y-1">
                  {machines.map((e) => {
                    const light = engines.get(e.id)?.state ?? "off";
                    return (
                      <li key={e.id} className="flex items-start gap-1.5 text-xs">
                        <Cpu className="w-3 h-3 mt-0.5 shrink-0" style={{ color: e.color }} />
                        <span>
                          <span className="font-medium text-gray-200">{e.label}</span>
                          <span
                            className={`ml-1.5 inline-block w-1.5 h-1.5 rounded-full align-middle ${
                              light === "busy" ? "bg-amber-400 animate-pulse" : light === "on" ? "bg-emerald-400" : "bg-gray-600"
                            }`}
                            title={light}
                          />
                          <span className="text-gray-400"> — {e.does}</span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
              {d.id === "huddle" && (
                <p className="text-xs text-gray-400 mt-1">
                  The agents a question touches meet here; the Observer chairs and decides, and you may overrule after.
                </p>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

export default FloorPlanPanel;
