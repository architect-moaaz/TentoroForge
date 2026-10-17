// The component kit — things that sit over the screen: a bottom `Sheet` (a
// picker, a form in a corner of a flow) and a centred `Dialog` (a yes/no
// question). Both are the platform's own Modal, so focus, the Android back
// button and screen readers behave; tapping the dim backdrop closes either.
//
//   <Sheet visible={open} title="Status" onClose={() => setOpen(false)}> …options… </Sheet>
//   <Dialog visible message="Delete this order?" confirmLabel="Delete" variant="danger" onConfirm={…} onCancel={…} />

import * as React from "react";
import { Modal, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { Button, type ButtonVariant } from "./Button";

export interface SheetProps {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children?: React.ReactNode;
}

export function Sheet({ visible, onClose, title, children }: SheetProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={{ flex: 1, justifyContent: "flex-end" }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={onClose} style={{ ...absoluteFill, backgroundColor: theme.alpha("foreground", 0.4) }} />
        <View style={{ maxHeight: "80%", backgroundColor: theme.colors.card, borderTopLeftRadius: theme.radii.lg, borderTopRightRadius: theme.radii.lg, paddingBottom: insets.bottom + theme.space.lg }}>
          <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: theme.space.lg, paddingTop: theme.space.lg, paddingBottom: theme.space.sm }}>
            <Text variant="heading" style={{ flex: 1 }}>{title ?? ""}</Text>
            <Button variant="ghost" size="sm" onPress={onClose}>Done</Button>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingHorizontal: theme.space.lg, paddingBottom: theme.space.sm, gap: theme.space.sm }}>
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const absoluteFill = { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 } as const;

export interface DialogProps {
  visible: boolean;
  message: string;
  title?: string;
  confirmLabel?: string;
  variant?: ButtonVariant;
  onConfirm: () => void;
  onCancel: () => void;
}

/** A question the person answers before something happens. */
export function Dialog({ visible, message, title, confirmLabel = "OK", variant = "primary", onConfirm, onCancel }: DialogProps) {
  const theme = useTheme();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel} statusBarTranslucent>
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: theme.space.xl }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Cancel" onPress={onCancel} style={{ ...absoluteFill, backgroundColor: theme.alpha("foreground", 0.4) }} />
        <View accessibilityViewIsModal style={{ width: "100%", maxWidth: 420, backgroundColor: theme.colors.card, borderRadius: theme.radii.lg, padding: theme.space.xl, gap: theme.space.lg }}>
          {title ? <Text variant="heading">{title}</Text> : null}
          <Text>{message}</Text>
          <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: theme.space.sm }}>
            <Button variant="outline" onPress={onCancel}>Cancel</Button>
            <Button variant={variant === "outline" || variant === "ghost" ? "primary" : variant} onPress={onConfirm}>{confirmLabel}</Button>
          </View>
        </View>
      </View>
    </Modal>
  );
}
