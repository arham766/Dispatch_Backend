import { Resend } from 'resend';
import { NextResponse } from 'next/server';

// Initialize Resend with your API Key
const resend = new Resend('re_xxxxxxxxx');

export async function POST() {
  try {
    const data = await resend.emails.send({
      from: 'onboarding@resend.dev',
      to: 'aluthra26@wabash.edu',
      subject: 'Hello World',
      html: '<p>Congrats on sending your <strong>first email</strong>!</p>'
    });

    return NextResponse.json({ success: true, data });
  } catch (error) {
    return NextResponse.json({ success: false, error }, { status: 500 });
  }
}
