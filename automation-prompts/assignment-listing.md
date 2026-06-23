# Assignment listing automation prompt

Use this guidance when producing compact Slack assignment lists for consultant
matching.

## Goal

Post short Slack list items that help people quickly scan new IT assignments and
request a consultant fit analysis in a thread.

## Required Slack item content

Each assignment list item must include:

- `[assignment-id]`
- assignment title
- location and/or main role summary
- full online assignment ad link
- suggested consultant matches by first name or canonical name

Keep each item compact. Do not include sensitive consultant details, internal
notes, private profile content, availability constraints, or CV weaknesses in
the assignment list.

## Matching names

Use consultant names that can be resolved against `consultants.yaml`.

Prefer first names when they are unambiguous in the consultant data. Use the
canonical name when a first name could refer to more than one consultant.

## Example Slack output

```text
[12345] Senior Front-end Developer, Stockholm
<https://example.com/ad/12345|View ad>
Good matches: Joel, Lena
```

## Follow-up command

Slack users can request detailed analysis by replying in the thread:

```text
fit 12345 Joel
```
