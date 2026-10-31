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
						label: 'Guide',
						link: '/overview/',
						icon: 'open-book',
						items: [
							{ label: 'Get started', items: ['overview', 'installation', 'quickstart'] },
							{ label: 'Concepts', items: ['concepts/loop', 'concepts/levels'] },
							{
								label: 'Plugin architecture',
								items: [
									'architecture',
									'architecture/events',
									'architecture/analysis',
									'architecture/trust',
								],
							},
							{
								label: 'Connect an agent',
								items: ['connect/chatgpt-dots', 'connect/grok-bot', 'connect/local-agents', 'connect/instructions'],
							},
							{ label: 'Other modes', items: ['modes/read', 'modes/run'] },
						],
					},
					{
						label: 'MCP reference',
						link: '/reference/tools/',
						icon: 'puzzle',
						items: ['reference/tools', 'reference/report', 'reference/server'],
					},
					{
						label: 'CLI reference',
						link: '/cli/',
						icon: 'seti:shell',
						items: ['cli'],
					},
					{
						label: 'Developers',
						link: '/developers/',
						icon: 'setting',
						items: ['developers', 'developers/contributing'],
					},
				]),
			],
		}),
	],
});
