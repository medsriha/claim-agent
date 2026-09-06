import { Fragment } from "react";

interface MarkdownProps {

  text: string;

  className?: string;
}

export function Markdown({ text, className }: MarkdownProps): React.JSX.Element {
  const blocks = readBlocks(text);
  return (
    <div className={className}>
      {blocks.map((block, index) => (
        <Block key={index} block={block} />
      ))}
    </div>
  );
}

type Block =
  | { readonly kind: "paragraph"; readonly lines: string[] }
  | { readonly kind: "heading"; readonly level: number; readonly text: string }
  | { readonly kind: "list"; readonly ordered: boolean; readonly items: string[] }
  | { readonly kind: "code"; readonly lines: string[] }
  | { readonly kind: "table"; readonly header: string[]; readonly rows: string[][] };

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const FENCE = /^\s*```/;
/** A table row: at least one bar, and a bar at each end. */
const ROW = /^\s*\|(.*)\|\s*$/;
/** The line under a table's heading, which is dashes and colons and nothing else. */
const RULE = /^\s*\|[\s|:-]+\|\s*$/;

/**
 * Split text into the blocks it is made of, in the order they were written.
 *
 * Reads line by line rather than by pattern-matching the whole text, so a line that is not
 * anything in particular is simply part of the paragraph it sits in. That is what makes
 * ordinary prose — which is most of what arrives — cost nothing to read.
 */
function readBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = text.split("\n");
  let paragraph: string[] = [];

  // A paragraph ends when something else begins, so every branch below closes it first.
  const endParagraph = (): void => {
    if (paragraph.length > 0) {
      blocks.push({ kind: "paragraph", lines: paragraph });
      paragraph = [];
    }
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";

    if (FENCE.test(line)) {
      endParagraph();
      const code: string[] = [];
      index += 1;
      // A fence nobody closed runs to the end of the text. Showing the rest as code beats
      // dropping it, and it is visible enough that the reader can see what happened.
      while (index < lines.length && !FENCE.test(lines[index] ?? "")) {
        code.push(lines[index] ?? "");
        index += 1;
      }
      blocks.push({ kind: "code", lines: code });
      continue;
    }

    if (line.trim() === "") {
      endParagraph();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      endParagraph();
      blocks.push({
        kind: "heading",
        level: (heading[1] ?? "#").length,
        text: heading[2] ?? "",
      });
      continue;
    }

    const bullet = BULLET.exec(line);
    const item = bullet ?? NUMBERED.exec(line);
    if (item) {
      endParagraph();
      const ordered = bullet === null;
      const previous = blocks[blocks.length - 1];
      // Consecutive items of the same sort are one list. A bullet list interrupted by a
      // numbered one becomes two lists, which is what was written.
      if (previous?.kind === "list" && previous.ordered === ordered) {
        previous.items.push(item[1] ?? "");
      } else {
        blocks.push({ kind: "list", ordered, items: [item[1] ?? ""] });
      }
      continue;
    }

    // A table is read whole rather than line by line, because a row on its own means
    // nothing and the line of dashes under the heading is not content. A row with no
    // rule under it is left as ordinary text, which is what it is.
    const row = ROW.exec(line);
    if (row && RULE.test(lines[index + 1] ?? "")) {
      endParagraph();
      const header = cells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && ROW.test(lines[index] ?? "")) {
        rows.push(cells(lines[index] ?? ""));
        index += 1;
      }
      index -= 1;
      blocks.push({ kind: "table", header, rows });
      continue;
    }

    paragraph.push(line);
  }

  endParagraph();
  return blocks;
}

/** Draw one block as the thing it describes. */
function Block({ block }: { block: Block }): React.JSX.Element {
  switch (block.kind) {
    case "paragraph":
      return (
        <p className="md-paragraph">
          {block.lines.map((line, index) => (
            <Fragment key={index}>
              {index > 0 && <br />}
              <Inline text={line} />
            </Fragment>
          ))}
        </p>
      );

    case "heading":
      return <Heading level={block.level} text={block.text} />;

    case "list":
      return block.ordered ? (
        <ol className="md-list">
          {block.items.map((item, index) => (
            <li key={index}>
              <Inline text={item} />
            </li>
          ))}
        </ol>
      ) : (
        <ul className="md-list">
          {block.items.map((item, index) => (
            <li key={index}>
              <Inline text={item} />
            </li>
          ))}
        </ul>
      );

    case "code":
      // Code is shown as it was written, formatting included, and nothing inside it is
      // read as markdown — that is the point of putting something in a code block.
      return (
        <pre className="md-code">
          <code>{block.lines.join("\n")}</code>
        </pre>
      );

    case "table":
      // Wrapped in something that scrolls on its own, so a wide table never makes the
      // page itself scroll sideways.
      return (
        <div className="md-table-frame">
          <table className="md-table">
            <thead>
              <tr>
                {block.header.map((cell, index) => (
                  <th key={index}>
                    <Inline text={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, index) => (
                    <td key={index}>
                      <Inline text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
}

/**
 * Split one table row into its cells.
 *
 * A bar that was escaped is part of the text rather than the edge of a cell, so it is put
 * back as an ordinary bar once the splitting is done — which is what lets a finding say
 * "two columns | one row" without shifting every column after it.
 */
function cells(line: string): string[] {
  const inside = ROW.exec(line)?.[1] ?? "";
  return inside
    .split(/(?<!\\)\|/)
    .map((cell) => cell.replace(/\\\|/g, "|").trim());
}

/**
 * A heading, pushed down to sit under the headings the page already has.
 *
 * A remark appears inside a conversation that has its own heading levels, so a `#` in it
 * is a heading within that step rather than a heading of the page. Levels below the
 * smallest heading available all draw as the smallest one.
 */
function Heading({ level, text }: { level: number; text: string }): React.JSX.Element {
  const body = <Inline text={text} />;
  if (level <= 1) {
    return <h4 className="md-heading">{body}</h4>;
  }
  if (level === 2) {
    return <h5 className="md-heading">{body}</h5>;
  }
  return <h6 className="md-heading">{body}</h6>;
}

/**
 * The markings that happen inside a line: `**bold**` and `__bold__`, `*italic*` and
 * `_italic_`, and `` `code` ``.
 *
 * Everything between them is untouched text, and two rules keep it that way — both of them
 * how markdown itself behaves, and both of them things this system runs into constantly:
 *
 * - **A mark must sit against its text.** `5 * 3 * 2` is multiplication, not emphasis,
 *   because the asterisks have spaces after them.
 * - **An underscore inside a word is part of the word.** `claim_line_id` and
 *   `list_attachments` are how everything in this system is named, and they must survive
 *   being written in a sentence.
 */
const INLINE = new RegExp(
  [
    "`([^`]+)`", // `code`
    "\\*\\*(\\S(?:[^*]*\\S)?)\\*\\*",
    "\\*(\\S(?:[^*]*\\S)?)\\*",
    "(?<![A-Za-z0-9_])__(\\S(?:[^_]*\\S)?)__(?![A-Za-z0-9_])",
    "(?<![A-Za-z0-9_])_(\\S(?:[^_]*\\S)?)_(?![A-Za-z0-9_])",
  ].join("|"),
  "g",
);

function Inline({ text }: { text: string }): React.JSX.Element {
  const pieces: React.JSX.Element[] = [];
  let plainFrom = 0;

  for (const match of text.matchAll(INLINE)) {
    const at = match.index;
    if (at > plainFrom) {
      pieces.push(<span key={plainFrom}>{text.slice(plainFrom, at)}</span>);
    }

    const [, code, starBold, starItalic, underscoreBold, underscoreItalic] = match;
    const bold = starBold ?? underscoreBold;
    if (code !== undefined) {
      pieces.push(
        <code key={at} className="md-inline-code">
          {code}
        </code>,
      );
    } else if (bold !== undefined) {
      pieces.push(<strong key={at}>{bold}</strong>);
    } else {
      pieces.push(<em key={at}>{starItalic ?? underscoreItalic}</em>);
    }

    plainFrom = at + match[0].length;
  }

  if (plainFrom < text.length) {
    pieces.push(<span key={plainFrom}>{text.slice(plainFrom)}</span>);
  }
  return <>{pieces}</>;
}
