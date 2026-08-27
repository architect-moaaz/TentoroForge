import { cva, type VariantProps } from "class-variance-authority";

/**
 * Canonical CVA template for library components.
 *
 * Pattern: define a `<Component>Variants` factory at module level. Components
 * import it and call `buttonVariants({ variant, size })` to compose classes.
 * New variant axes are added here, not in the component body.
 *
 * Tokens are referenced via Tailwind's design-system color names which alias
 * to CSS variables compiled from defaultTokens. To add density / elevation /
 * radius axes (Phase 2), extend `variants` with new keys.
 */
export const buttonVariants = cva(
  // base classes — applied to every variant
  "inline-flex items-center justify-center gap-2 font-medium whitespace-nowrap " +
  "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        primary:   "bg-primary text-primary-foreground hover:bg-primary/90",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        // Accent — the second brand hue as a resting-state background.
        // Use for secondary CTAs where "outline" or "ghost" would feel
        // too quiet but "primary" would double up with another primary
        // action already on the page (e.g. an "Invite instructor"
        // button next to the primary "New booking"). Consumes the same
        // shadcn --accent / --accent-foreground CSS vars Badge + Tag
        // use, so all three components stay in visual sync.
        accent:    "bg-accent text-accent-foreground hover:bg-accent/90",
        // Ghost variant gets a hairline border at rest so it reads as a
        // tappable affordance. Pure-transparent ghost (no border) blends into
        // the page and looks like a failed render — common feedback on
        // card-row "View" buttons.
        ghost:     "bg-transparent text-foreground border border-border/60 hover:bg-accent hover:text-accent-foreground hover:border-border",
        danger:    "bg-destructive text-destructive-foreground hover:bg-destructive/90",
      },
      size: {
        sm: "h-8  px-3 text-xs",
        md: "h-10 px-4 text-sm",
        lg: "h-12 px-6 text-base",
      },
      /** When true the button is icon-only: remove horizontal padding and make it square. */
      iconOnly: {
        true:  "",
        false: "",
      },
    },
    compoundVariants: [
      // icon-only sizing: square button, no horizontal padding
      { iconOnly: true, size: "sm", class: "w-8  px-0" },
      { iconOnly: true, size: "md", class: "w-10 px-0" },
      { iconOnly: true, size: "lg", class: "w-12 px-0" },
    ],
    defaultVariants: {
      variant: "primary",
      size: "md",
      iconOnly: false,
    },
  },
);

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;
