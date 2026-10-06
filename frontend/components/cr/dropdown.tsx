"use client";
import { Check, ChevronDown } from "lucide-react";
import { Select as SelectPrimitive } from "radix-ui";
import { Children, Fragment, isValidElement, type ComponentType, type ReactElement, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * App-styled dropdown (CodeRabbit look: dark popover, hairline border, orange check on the chosen item)
 * that is a drop-in replacement for a native <select>: it takes the same `value` / `onChange` / `<option>`
 * children, so call sites only swap the tag. Built on Radix Select, so it keeps the combobox role,
 * keyboard navigation and typeahead.
 */

type Opt = { value: string; label: ReactNode; text: string; disabled?: boolean };

// Radix reserves "" for "no value"; map it to a sentinel and back.
const EMPTY = "__empty__";
const enc = (v: string) => (v === "" ? EMPTY : v);
const dec = (v: string) => (v === EMPTY ? "" : v);

function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function collect(children: ReactNode, out: Opt[] = []): Opt[] {
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const el = child as ReactElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>;
    if (el.type === Fragment || el.type === "optgroup") {
      collect(el.props.children, out);
    } else if (el.type === "option") {
      const text = textOf(el.props.children);
      out.push({
        value: el.props.value !== undefined ? String(el.props.value) : text,
        label: el.props.children,
        text,
        disabled: el.props.disabled,
      });
    }
  });
  return out;
}

export type DropdownProps = {
  value?: string | number;
  defaultValue?: string | number;
  /** Native-compatible change handler: receives `{ target: { value } }`. */
  onChange?: (e: { target: { value: string } }) => void;
  onValueChange?: (value: string) => void;
  children: ReactNode;
  id?: string;
  name?: string;
  disabled?: boolean;
  required?: boolean;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "true" | "false";
  /** Muted text before the value inside the trigger, e.g. "Show:" or "Action:". */
  prefix?: ReactNode;
  icon?: ComponentType<{ className?: string }>;
  size?: "sm" | "default";
  placeholder?: string;
  /** Classes for the trigger button. */
  className?: string;
  contentClassName?: string;
  align?: "start" | "center" | "end";
};

export function Dropdown({
  value,
  defaultValue,
  onChange,
  onValueChange,
  children,
  id,
  name,
  disabled,
  required,
  prefix,
  icon: Icon,
  size = "default",
  placeholder,
  className,
  contentClassName,
  align = "start",
  ...aria
}: DropdownProps) {
  const options = collect(children);
  const controlled = value !== undefined;
  const handle = (v: string) => {
    const out = dec(v);
    onValueChange?.(out);
    onChange?.({ target: { value: out } });
  };

  return (
    <SelectPrimitive.Root
      value={controlled ? enc(String(value)) : undefined}
      defaultValue={defaultValue !== undefined ? enc(String(defaultValue)) : undefined}
      onValueChange={handle}
      disabled={disabled}
      required={required}
      name={name}
    >
      <SelectPrimitive.Trigger
        id={id}
        {...aria}
        className={cn(
          "group/dd inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-md border border-input bg-card pr-2 pl-3 text-left text-sm whitespace-nowrap text-foreground transition-colors outline-none select-none",
          "hover:bg-accent focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 data-[state=open]:bg-accent",
          "disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive data-placeholder:text-muted-foreground",
          size === "sm" ? "h-7 text-[13px]" : "h-8",
          className,
        )}
      >
        {Icon ? <Icon aria-hidden className="size-4 shrink-0 text-muted-foreground" /> : null}
        {prefix ? <span className="shrink-0 text-muted-foreground">{prefix}</span> : null}
        <span className="min-w-0 flex-1 truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon asChild>
          <ChevronDown
            aria-hidden
            className="size-4 shrink-0 text-muted-foreground transition-transform duration-150 group-data-[state=open]/dd:rotate-180"
          />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          align={align}
          className={cn(
            "z-50 max-h-[min(var(--radix-select-content-available-height),340px)] min-w-(--radix-select-trigger-width) overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-xl shadow-black/40",
            "origin-(--radix-select-content-transform-origin) data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-1 data-[side=top]:slide-in-from-bottom-1",
            contentClassName,
          )}
        >
          <SelectPrimitive.ScrollUpButton className="flex h-6 items-center justify-center text-muted-foreground">
            <ChevronDown className="size-3.5 rotate-180" aria-hidden />
          </SelectPrimitive.ScrollUpButton>
          <SelectPrimitive.Viewport className="p-1">
            {options.map((o) => (
              <SelectPrimitive.Item
                key={o.value}
                value={enc(o.value)}
                disabled={o.disabled}
                textValue={o.text}
                className={cn(
                  "relative flex h-8 cursor-pointer items-center rounded-md pr-8 pl-2.5 text-sm text-muted-foreground outline-none select-none",
                  "data-[highlighted]:bg-accent data-[highlighted]:text-foreground data-[state=checked]:text-foreground data-[state=checked]:font-medium",
                  "data-[disabled]:cursor-not-allowed data-[disabled]:text-faint",
                )}
              >
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-2.5 inline-flex">
                  <Check className="size-3.5 text-primary" aria-hidden />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
          <SelectPrimitive.ScrollDownButton className="flex h-6 items-center justify-center text-muted-foreground">
            <ChevronDown className="size-3.5" aria-hidden />
          </SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
