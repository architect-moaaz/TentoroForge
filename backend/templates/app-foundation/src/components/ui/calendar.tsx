"use client";

/**
 * A month calendar for choosing a day or a range — booking a table, a
 * delivery slot's day, a report's dates. react-day-picker, drawn with the
 * app's token classes rather than its own stylesheet.
 */
import * as React from "react";
import { DayPicker } from "react-day-picker";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

function Calendar({ className, classNames, showOutsideDays = true, ...props }: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-3", className)}
      classNames={{
        months: "relative flex flex-col gap-4 sm:flex-row",
        month: "flex flex-col gap-4",
        month_caption: "flex h-9 items-center justify-center text-sm font-medium",
        nav: "absolute inset-x-0 top-0 flex items-center justify-between",
        button_previous:
          "inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted disabled:opacity-40",
        button_next:
          "inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted disabled:opacity-40",
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday: "w-9 text-[0.8rem] font-normal text-muted-foreground",
        week: "mt-1 flex w-full",
        day: "relative h-9 w-9 p-0 text-center text-sm",
        day_button:
          "inline-flex h-9 w-9 items-center justify-center rounded-md font-normal transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected: "[&>button]:bg-primary [&>button]:text-primary-foreground [&>button:hover]:bg-primary",
        range_middle: "[&>button]:rounded-none [&>button]:bg-accent-subtle [&>button]:text-foreground",
        today: "[&>button]:font-semibold [&>button]:text-accent",
        outside: "text-muted-foreground opacity-50",
        disabled: "text-muted-foreground opacity-40",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation }) =>
          orientation === "left" ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />,
      }}
      {...props}
    />
  );
}
Calendar.displayName = "Calendar";

export { Calendar };
