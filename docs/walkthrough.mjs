// Manual flow of the MVP, driven in a real browser, saving screenshots for the README.
import { chromium } from 'playwright'
const BASE = 'http://localhost:5173'
const OUT = process.argv[2]
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1180, height: 800 }, locale: 'pt-BR' })
const page = await ctx.newPage()
const shot = (name, p = page, opts = {}) => p.screenshot({ path: `${OUT}/${name}.png`, ...opts })
const login = async (email) => {
  await page.goto(`${BASE}/login`)
  await page.fill('#email', email); await page.fill('#password', 'senha-12345')
  await page.click('button.primary'); await page.waitForSelector('.topbar')
}
const logout = async () => { await page.click('text=Sair'); await page.waitForSelector('.login') }
const ask = async (q) => {
  await page.fill('input[aria-label="Pergunta"]', q)
  await page.click('text=Perguntar')
}
const waitAnswer = (n) => page.waitForFunction((n) => document.querySelectorAll('.msg-bot .card:not(.thinking)').length >= n, n, { timeout: 240000 })

await page.goto(`${BASE}/login`); await shot('01-login')
await login('novato@alvorada.example'); await page.waitForSelector('.card'); await shot('02-tutoriais')
await page.click('text=Política de Férias'); await page.waitForSelector('.md'); await shot('03-leitura-tutorial')

await page.click('text=Assistente'); await page.waitForSelector('.composer')
await ask('Com quantos dias de antecedência preciso pedir férias?')
await page.waitForSelector('.thinking'); await page.waitForTimeout(500); await shot('04-carregando')
await waitAnswer(1); await shot('05-resposta-com-fontes')

const [popup] = await Promise.all([ctx.waitForEvent('page'), page.click('.msg-bot .cite')])
await popup.waitForSelector('.passage'); await popup.waitForTimeout(500)
await popup.setViewportSize({ width: 1180, height: 800 }); await shot('06-citacao-aberta', popup); await popup.close()

await ask('Como funciona o plano odontológico?'); await waitAnswer(2)
await ask('Qual é o plano odontológico da empresa?'); await waitAnswer(3)
await ask('Tem plano odontológico para os colaboradores?'); await waitAnswer(4)
await shot('07-recusa-com-responsavel')

await ask('Qual é o valor do auxílio home office mensal?'); await waitAnswer(5)
await page.click('button:has-text("Isso não respondeu")'); await page.waitForSelector('text=Obrigado')
await shot('08-feedback-enviado')
await ask('Qual a faixa salarial do nível N3?'); await waitAnswer(6)
await shot('09-restrito-recusa')
await logout()

await login('gestor.rh@alvorada.example')
await page.click('text=Painel'); await page.waitForSelector('text=Lacunas de documentação'); await page.waitForTimeout(800)
await shot('10-painel-gestor', page, { fullPage: true })
await page.click('text=Gerenciar documentos'); await page.waitForSelector('table'); await shot('11-gerenciar-documentos')
await page.click('text=Política de Férias'); await page.waitForSelector('#content'); await shot('12-editor-documento', page, { fullPage: true })
await logout()

await login('admin@alvorada.example')
await page.click('text=Administração'); await page.waitForSelector('table'); await shot('13-administracao', page, { fullPage: true })
await browser.close()
console.log('ok')
