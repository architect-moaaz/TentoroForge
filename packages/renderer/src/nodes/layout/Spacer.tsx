import { tokenToCssVar } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";

export function Spacer({ node }: { node: any }) {
  const size = node.props.size;
  const slotProps = applyStyleSlot(node.style);
  return (
    <div
      data-node-id={node.id}
      style={{
        width: `var(${tokenToCssVar(size)})`,
        height: `var(${tokenToCssVar(size)})`,
        flexShrink: 0,
        ...slotProps.style,
      }}
      data-motion={slotProps["data-motion"]}
    />
  );
}
