// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightSidebarTopics from 'starlight-sidebar-topics';

export default defineConfig({
	site: 'https://always-on-intelligence.github.io',
	base: '/HALO',
	integrations: [
		starlight({
			title: 'HALO',
			description: 'HALO plugs into a personal agent through MCP and shows how its loop closes.',
			defaultLocale: 'root',
			locales: {
				root: { label: 'English', lang: 'en' },
				'zh-cn': { label: '简体中文', lang: 'zh-CN' },
			},
			logo: { src: './src/assets/mark.svg', alt: 'HALO' },
			favicon: '/favicon.svg',
			customCss: [
				'@fontsource-variable/geist',
				'@fontsource-variable/geist-mono',
				'@fontsource-variable/space-grotesk',
				'./src/styles/theme.css',
			],
			components: {
				Header: './src/components/Header.astro',
				Sidebar: './src/components/Sidebar.astro',
				SiteTitle: './src/components/SiteTitle.astro',
				ThemeSelect: './src/components/ThemeToggle.astro',
				LanguageSelect: './src/components/LanguageToggle.astro',
			},
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/Always-On-Intelligence/HALO' }],
			expressiveCode: {
				themes: ['github-light', 'github-dark'],
				styleOverrides: {
					borderRadius: '6px',
					borderColor: 'var(--halo-line)',
					codeFontFamily: "'Geist Mono Variable', ui-monospace, SFMono-Regular, Menlo, monospace",
					uiFontFamily: "'Geist Variable', system-ui, sans-serif",
					frames: { shadowColor: 'transparent' },
				},
			},
			plugins: [
				starlightSidebarTopics([
					{
						label: { en: 'Guide', 'zh-cn': '指南' },
						link: '/overview/',
						icon: 'open-book',
						items: [
							{ label: 'Get started', translations: { 'zh-CN': '开始使用' }, items: ['overview', 'installation', 'quickstart'] },
							{ label: 'Concepts', translations: { 'zh-CN': '概念' }, items: ['concepts/loop', 'concepts/levels'] },
							{
								label: 'Plugin architecture',
								translations: { 'zh-CN': '插件架构' },
								items: [
									'architecture',
									'architecture/events',
									'architecture/analysis',
									'architecture/trust',
								],
							},
							{
								label: 'Connect an agent',
								translations: { 'zh-CN': '接入智能体' },
								items: ['connect/chatgpt-dots', 'connect/grok-bot', 'connect/local-agents', 'connect/instructions'],
							},
							{ label: 'Other modes', translations: { 'zh-CN': '其他模式' }, items: ['modes/read', 'modes/run'] },
						],
					},
					{
						label: { en: 'Survey results', 'zh-cn': '论文结果' },
						link: '/results/',
						icon: 'document',
						items: ['results', 'results/research', 'results/products'],
					},
					{
						label: { en: 'MCP reference', 'zh-cn': 'MCP 参考' },
						link: '/reference/tools/',
						icon: 'puzzle',
						items: ['reference/tools', 'reference/report', 'reference/server'],
					},
					{
						label: { en: 'CLI reference', 'zh-cn': '命令行参考' },
						link: '/cli/',
						icon: 'seti:shell',
						items: ['cli'],
					},
					{
						label: { en: 'Developers', 'zh-cn': '开发者' },
						link: '/developers/',
						icon: 'setting',
						items: ['developers', 'developers/contributing'],
					},
				]),
			],
		}),
	],
});
