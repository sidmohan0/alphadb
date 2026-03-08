export const ansi = {
  hideCursor: "\x1b[?25l",
  showCursor: "\x1b[?25h",
  altScreen: "\x1b[?1049h",
  mainScreen: "\x1b[?1049l",
  clear: "\x1b[2J\x1b[H",
  reset: "\x1b[0m",
};

export function moveTo(row: number, col: number): string {
  return `\x1b[${row};${col}H`;
}

export function color(...codes: number[]): string {
  return `\x1b[${codes.join(";")}m`;
}

export function stripAnsi(value: string): string {
  return value.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "");
}

export function visibleWidth(value: string): number {
  return stripAnsi(value).length;
}

export function truncate(value: string, width: number): string {
  if (width <= 0) {
    return "";
  }

  if (value.length <= width) {
    return value.padEnd(width, " ");
  }

  if (width === 1) {
    return value.slice(0, 1);
  }

  return `${value.slice(0, width - 1)}…`;
}

export function padAnsi(value: string, width: number): string {
  const visible = visibleWidth(value);
  if (visible >= width) {
    return value;
  }

  return `${value}${" ".repeat(width - visible)}`;
}

export function fitAnsi(value: string, width: number): string {
  if (width <= 0) {
    return "";
  }

  if (visibleWidth(value) <= width) {
    return padAnsi(value, width);
  }

  if (width === 1) {
    return "…";
  }

  let output = "";
  let visible = 0;
  let index = 0;

  while (index < value.length && visible < width - 1) {
    if (value[index] === "\x1b") {
      const match = value.slice(index).match(/^\x1b\[[0-9;?]*[A-Za-z]/);
      if (match) {
        output += match[0];
        index += match[0].length;
        continue;
      }
    }

    output += value[index];
    visible += 1;
    index += 1;
  }

  return `${output}…${ansi.reset}`;
}
