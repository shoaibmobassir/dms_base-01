import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Options = {
  title: string;
  description?: string;
  /** Button label; say what happens ("Delete argument"), not "OK". */
  confirmLabel?: string;
  destructive?: boolean;
};

const ConfirmContext = createContext<((o: Options) => Promise<boolean>) | null>(null);

/** Ask before something that cannot be undone: `if (await confirm({ title: "Delete this argument?" })) …`. */
export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within ConfirmProvider");
  return ctx;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<Options | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback((o: Options) => {
    setOptions(o);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);
  const settle = (ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setOptions(null);
  };
  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Dialog open={!!options} onOpenChange={(open) => !open && settle(false)}>
        <DialogContent className="max-w-sm" data-testid="confirm-dialog">
          <DialogHeader>
            <DialogTitle>{options?.title}</DialogTitle>
            {options?.description && <DialogDescription>{options.description}</DialogDescription>}
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => settle(false)}>
              Cancel
            </Button>
            <Button
              variant={options?.destructive === false ? "default" : "destructive"}
              onClick={() => settle(true)}
              data-testid="confirm-accept"
            >
              {options?.confirmLabel ?? "Confirm"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  );
}
