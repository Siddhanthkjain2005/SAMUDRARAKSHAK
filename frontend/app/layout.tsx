import type { Metadata } from 'next';
import './globals.css';
import './refinements.css';
export const metadata: Metadata = {title:'SamudraRakshak AI · Ocean Operations',description:'One ocean. One intelligence layer. Three autonomous missions.',icons:{icon:'/favicon.svg'}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
