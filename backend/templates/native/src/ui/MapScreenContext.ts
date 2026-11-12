// The component kit — what a map screen tells the sheet that sits on it, and what the sheet tells back. Kept apart from
// both so neither imports the other.

import * as React from "react";

export interface MapScreenLayout {
  /** How tall the area the sheet may use is (the whole screen under the top bar). 0 until measured. */
  room: number;
  /** The sheet came to rest showing this many points: the map frames and centres above it, the buttons ride on it. */
  reportShown: (shown: number) => void;
}

export const MapScreenContext = React.createContext<MapScreenLayout>({ room: 0, reportShown: () => undefined });
