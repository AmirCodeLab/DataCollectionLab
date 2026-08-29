/** Plain table cells. Logical properties throughout, so RTL just works. */

import type { ReactNode } from "react";

export function Th({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <th className={`px-2 py-2 text-start font-medium ${className ?? ""}`}>
      {children}
    </th>
  );
}

export function Td({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <td className={`px-2 py-2 align-top ${className ?? ""}`}>{children}</td>
  );
}
