import { iconButtonAriaLabel } from "./iconbutton-aria-label";
import { repeatNeedsKeypath } from "./repeat-needs-keypath";
import { cardTooManyChildren } from "./card-too-many-children";
import { textWithoutContent } from "./text-without-content";
import { unknownTokenReference } from "./unknown-token-reference";
import type { Rule } from "../types";

export const rules: Rule[] = [
  iconButtonAriaLabel,
  repeatNeedsKeypath,
  cardTooManyChildren,
  textWithoutContent,
  unknownTokenReference,
];
