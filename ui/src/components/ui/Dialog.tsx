import type { ReactNode } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

/** A modal: focus is trapped, Esc and the close button dismiss it, focus returns to whatever opened it. */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-[60] bg-black/50" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-[61] w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-4 shadow-xl">
          <div className="flex items-start gap-2">
            <RadixDialog.Title className="text-[15px] font-semibold text-tx">{title}</RadixDialog.Title>
            <RadixDialog.Close aria-label="Close" className="ml-auto rounded p-0.5 text-tx3 hover:text-tx focus-visible:outline-2">
              <X size={16} aria-hidden />
            </RadixDialog.Close>
          </div>
          {description && <RadixDialog.Description className="mt-1.5 text-[13px] text-tx2">{description}</RadixDialog.Description>}
          {children && <div className="mt-3">{children}</div>}
          {footer && <div className="mt-4 flex justify-end gap-2">{footer}</div>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

export const btnSecondary = "rounded-md border border-line px-3 py-1.5 text-[13px] text-tx2 hover:border-brand-bright hover:text-tx focus-visible:outline-2";
export const btnPrimary = "rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-white hover:bg-brand-bright disabled:opacity-60 focus-visible:outline-2";
