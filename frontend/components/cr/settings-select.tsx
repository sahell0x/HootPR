import { Dropdown, type DropdownProps } from "@/components/cr/dropdown";
import { cn } from "@/lib/utils";

/** Settings-form dropdown: the app-styled Dropdown sized like the Input primitive. */
export function SettingsSelect({ className, wrapperClassName, ...props }: DropdownProps & { wrapperClassName?: string }) {
  return (
    <span className={cn("inline-flex w-full sm:w-auto", wrapperClassName)}>
      <Dropdown className={cn("w-full min-w-40 bg-subtle", className)} {...props} />
    </span>
  );
}
