declare module "element-react" {
  import type { ComponentType, ReactNode } from "react";

  type ButtonProps = {
    children?: ReactNode;
    className?: string;
    disabled?: boolean;
    loading?: boolean;
    onClick?: () => void;
    size?: "large" | "small" | "mini";
    title?: string;
    type?: "primary" | "success" | "warning" | "danger" | "info" | "text";
  };

  export const Button: ComponentType<ButtonProps>;
}
