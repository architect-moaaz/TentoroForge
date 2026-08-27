/**
 * Form Input GrapeJS blocks — dedicated "Form Inputs" category
 * covering every common input type with labels and styling.
 */

import type { Editor } from "grapesjs";

const INPUT_CLS =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring";

export function registerInputBlocks(editor: Editor): void {
  const bm = editor.BlockManager;

  // ── Text ──────────────────────────────────────────────────────────────────

  bm.add("input-text", {
    label: "Text Box",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Label</label>
  <input type="text" class="${INPUT_CLS}" placeholder="Enter text…" />
</div>`,
  });

  bm.add("input-textarea", {
    label: "Textarea",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Message</label>
  <textarea rows="4" class="flex min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" placeholder="Enter message…"></textarea>
  <p class="text-xs text-muted-foreground">Helper text goes here.</p>
</div>`,
  });

  bm.add("input-password", {
    label: "Password",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Password</label>
  <input type="password" class="${INPUT_CLS}" placeholder="••••••••" />
</div>`,
  });

  bm.add("input-email", {
    label: "Email",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Email</label>
  <input type="email" class="${INPUT_CLS}" placeholder="you@example.com" />
</div>`,
  });

  bm.add("input-number", {
    label: "Number",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Amount</label>
  <input type="number" class="${INPUT_CLS}" placeholder="0" min="0" />
</div>`,
  });

  bm.add("input-phone", {
    label: "Phone",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Phone</label>
  <input type="tel" class="${INPUT_CLS}" placeholder="+1 (555) 000-0000" />
</div>`,
  });

  bm.add("input-url", {
    label: "URL",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Website</label>
  <input type="url" class="${INPUT_CLS}" placeholder="https://example.com" />
</div>`,
  });

  // ── Date / Time ───────────────────────────────────────────────────────────

  bm.add("input-date", {
    label: "Date Picker",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Date</label>
  <input type="date" class="${INPUT_CLS}" />
</div>`,
  });

  bm.add("input-time", {
    label: "Time",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Time</label>
  <input type="time" class="${INPUT_CLS}" />
</div>`,
  });

  bm.add("input-datetime", {
    label: "Date & Time",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Date &amp; Time</label>
  <input type="datetime-local" class="${INPUT_CLS}" />
</div>`,
  });

  // ── Select / Radio / Checkbox / Toggle ───────────────────────────────────

  bm.add("input-select", {
    label: "Select",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Select option</label>
  <select class="${INPUT_CLS}">
    <option value="">Choose…</option>
    <option value="a">Option A</option>
    <option value="b">Option B</option>
    <option value="c">Option C</option>
  </select>
</div>`,
  });

  bm.add("input-multiselect", {
    label: "Multi-select",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Select options</label>
  <select multiple class="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring min-h-[100px]">
    <option value="a">Option A</option>
    <option value="b">Option B</option>
    <option value="c">Option C</option>
    <option value="d">Option D</option>
  </select>
</div>`,
  });

  bm.add("input-checkbox", {
    label: "Checkbox",
    category: "Form Inputs",
    content: `<div class="flex items-center gap-2">
  <input type="checkbox" id="cb1" class="h-4 w-4 rounded border-input accent-primary" />
  <label for="cb1" class="text-sm font-medium leading-none cursor-pointer">Accept terms and conditions</label>
</div>`,
  });

  bm.add("input-checkbox-group", {
    label: "Checkbox Group",
    category: "Form Inputs",
    content: `<div class="space-y-2">
  <p class="text-sm font-medium">Options</p>
  <div class="flex items-center gap-2">
    <input type="checkbox" id="cbg1" class="h-4 w-4 rounded border-input accent-primary" />
    <label for="cbg1" class="text-sm cursor-pointer">Option 1</label>
  </div>
  <div class="flex items-center gap-2">
    <input type="checkbox" id="cbg2" class="h-4 w-4 rounded border-input accent-primary" />
    <label for="cbg2" class="text-sm cursor-pointer">Option 2</label>
  </div>
  <div class="flex items-center gap-2">
    <input type="checkbox" id="cbg3" class="h-4 w-4 rounded border-input accent-primary" />
    <label for="cbg3" class="text-sm cursor-pointer">Option 3</label>
  </div>
</div>`,
  });

  bm.add("input-radio", {
    label: "Radio Group",
    category: "Form Inputs",
    content: `<div class="space-y-2">
  <p class="text-sm font-medium">Choose one</p>
  <div class="flex items-center gap-2">
    <input type="radio" name="rg" id="r1" class="h-4 w-4 accent-primary" />
    <label for="r1" class="text-sm cursor-pointer">Option A</label>
  </div>
  <div class="flex items-center gap-2">
    <input type="radio" name="rg" id="r2" class="h-4 w-4 accent-primary" />
    <label for="r2" class="text-sm cursor-pointer">Option B</label>
  </div>
  <div class="flex items-center gap-2">
    <input type="radio" name="rg" id="r3" class="h-4 w-4 accent-primary" />
    <label for="r3" class="text-sm cursor-pointer">Option C</label>
  </div>
</div>`,
  });

  bm.add("input-toggle", {
    label: "Toggle / Switch",
    category: "Form Inputs",
    content: `<label class="flex items-center gap-3 cursor-pointer">
  <div class="relative">
    <input type="checkbox" class="sr-only peer" />
    <div class="w-10 h-6 rounded-full bg-muted peer-checked:bg-primary transition-colors"></div>
    <div class="absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4"></div>
  </div>
  <span class="text-sm font-medium">Enable feature</span>
</label>`,
  });

  bm.add("input-range", {
    label: "Range / Slider",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <div class="flex items-center justify-between">
    <label class="text-sm font-medium">Volume</label>
    <span class="text-sm text-muted-foreground">50</span>
  </div>
  <input type="range" min="0" max="100" value="50" class="w-full h-2 rounded-full accent-primary cursor-pointer" />
</div>`,
  });

  // ── File / Color ──────────────────────────────────────────────────────────

  bm.add("input-file", {
    label: "File Upload",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Upload file</label>
  <div class="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-input p-8 text-center cursor-pointer hover:bg-muted/50 transition-colors">
    <p class="text-sm text-muted-foreground">Drag &amp; drop or click to upload</p>
    <span class="text-xs text-muted-foreground">PNG, JPG, PDF up to 10 MB</span>
    <input type="file" class="hidden" />
  </div>
</div>`,
  });

  bm.add("input-color", {
    label: "Color Picker",
    category: "Form Inputs",
    content: `<div class="flex items-center gap-3">
  <label class="text-sm font-medium">Color</label>
  <input type="color" value="#6366f1" class="h-10 w-16 rounded-md border border-input cursor-pointer p-1" />
</div>`,
  });

  // ── Decorated inputs ──────────────────────────────────────────────────────

  bm.add("input-with-icon", {
    label: "Input with Icon",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Search</label>
  <div class="relative">
    <svg class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
    <input type="text" class="${INPUT_CLS} pl-9" placeholder="Search…" />
  </div>
</div>`,
  });

  bm.add("input-with-addon", {
    label: "Input with Addon",
    category: "Form Inputs",
    content: `<div class="space-y-1.5">
  <label class="text-sm font-medium leading-none">Website</label>
  <div class="flex rounded-md border border-input overflow-hidden focus-within:ring-2 focus-within:ring-ring">
    <span class="flex items-center px-3 bg-muted text-sm text-muted-foreground border-r">https://</span>
    <input type="text" class="flex-1 h-10 bg-background px-3 py-2 text-sm focus:outline-none" placeholder="yoursite.com" />
  </div>
</div>`,
  });

  bm.add("input-with-button", {
    label: "Input + Button",
    category: "Form Inputs",
    content: `<div class="flex gap-2">
  <input type="email" class="${INPUT_CLS}" placeholder="Enter email…" />
  <button class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 text-sm font-medium whitespace-nowrap">Subscribe</button>
</div>`,
  });

  // ── Full form patterns ─────────────────────────────────────────────────────

  bm.add("form-login", {
    label: "Login Form",
    category: "Form Inputs",
    content: `<form class="space-y-4 w-full max-w-sm" data-component="Form">
  <div class="space-y-1.5">
    <label class="text-sm font-medium">Email</label>
    <input type="email" class="${INPUT_CLS}" placeholder="you@example.com" data-bind="state:form.email" />
  </div>
  <div class="space-y-1.5">
    <label class="text-sm font-medium">Password</label>
    <input type="password" class="${INPUT_CLS}" placeholder="••••••••" data-bind="state:form.password" />
  </div>
  <button type="submit" class="w-full inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 text-sm font-medium">Sign in</button>
</form>`,
  });

  bm.add("form-contact", {
    label: "Contact Form",
    category: "Form Inputs",
    content: `<form class="space-y-4" data-component="Form">
  <div class="grid grid-cols-2 gap-4">
    <div class="space-y-1.5">
      <label class="text-sm font-medium">First name</label>
      <input type="text" class="${INPUT_CLS}" placeholder="John" />
    </div>
    <div class="space-y-1.5">
      <label class="text-sm font-medium">Last name</label>
      <input type="text" class="${INPUT_CLS}" placeholder="Doe" />
    </div>
  </div>
  <div class="space-y-1.5">
    <label class="text-sm font-medium">Email</label>
    <input type="email" class="${INPUT_CLS}" placeholder="you@example.com" />
  </div>
  <div class="space-y-1.5">
    <label class="text-sm font-medium">Message</label>
    <textarea rows="4" class="flex min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" placeholder="How can we help?"></textarea>
  </div>
  <button type="submit" class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 text-sm font-medium">Send message</button>
</form>`,
  });
}
