// Build and update the Vision One HUD page on the G2 using even-better-sdk.
// Layout: title line at the top, up to 4 content lines below.

import { EvenBetterSdk } from '@jappyjan/even-better-sdk'
import type { Frame } from './formatter'
import { MAX_LINES } from './formatter'

const PAGE_ID = 'v1smartglass-hud'

type Page = ReturnType<EvenBetterSdk['createPage']>
type TextElement = ReturnType<Page['addTextElement']>

type HudHandles = {
  title: TextElement
  body: TextElement[]
  render: () => Promise<void>
  update: (frame: Frame) => Promise<void>
}

let hud: HudHandles | null = null

export async function ensureHud(sdk: EvenBetterSdk): Promise<HudHandles> {
  if (hud) return hud

  const page = sdk.createPage(PAGE_ID)

  const title = page.addTextElement('V1 SMARTGLASS')
  title
    .setPosition((p) => p.setX(8).setY(4))
    .setSize((s) => s.setWidth(560).setHeight(28))

  const body: TextElement[] = []
  for (let i = 0; i < MAX_LINES - 1; i++) {
    const line = page.addTextElement('')
    line
      .setPosition((p) => p.setX(8).setY(36 + i * 22))
      .setSize((s) => s.setWidth(560).setHeight(22))
    body.push(line)
  }

  let firstRender = true

  const render = async (): Promise<void> => {
    if (firstRender) {
      await page.render()
      firstRender = false
      return
    }
    // Try incremental text update; fall back to full render if it fails.
    let ok = await title.updateWithEvenHubSdk()
    for (const line of body) {
      ok = (await line.updateWithEvenHubSdk()) && ok
    }
    if (!ok) {
      await page.render()
    }
  }

  const update = async (frame: Frame): Promise<void> => {
    title.setContent(frame.title)
    for (let i = 0; i < body.length; i++) {
      body[i].setContent(frame.lines[i] ?? '')
    }
    await render()
  }

  hud = { title, body, render, update }
  return hud
}

export function disposeHud(): void {
  hud = null
}
