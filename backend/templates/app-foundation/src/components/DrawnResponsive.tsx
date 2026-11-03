"use client";
// A screen the design draws for a phone and for a desktop is one page: it
// shows the phone drawing on a phone. One question, asked the same way by the
// page and by the frame around it.
import * as React from "react";

const PHONE = "(max-width: 767px)";

export function useIsPhone(): boolean {
  const [phone, setPhone] = React.useState(false);
  React.useEffect(() => {
    const query = window.matchMedia(PHONE);
    const update = () => setPhone(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return phone;
}
