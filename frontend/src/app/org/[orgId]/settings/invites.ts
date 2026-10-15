/** What an invitation did, in words the inviter can act on. A page file may
 *  export nothing but its page, so this lives beside it. */
export interface InviteOutcome {
  id: string;
  invite_email: string | null;
  role: string;
  invite_status: string;
  joined: boolean;
  emailed: boolean;
  invite_url: string;
}

/** The sentence that says what an invitation did, and the address to pass on
 *  when nobody was emailed. */
export function describeInvite(o: InviteOutcome): { text: string; link: string } {
  const who = o.invite_email ?? "them";
  if (o.joined) return { text: `${who} already had a Forge account and is a ${o.role} of this organisation now.`, link: "" };
  if (o.emailed) return { text: `An invitation was emailed to ${who}. They sign up with that address and the organisation is waiting for them.`, link: o.invite_url };
  if (o.invite_url) return { text: `No email service is set up here, so nothing was sent. Pass ${who} this sign-up address; the organisation is waiting for them once they sign up with it.`, link: o.invite_url };
  return { text: `${who} is invited. They sign up with that email address and the organisation is waiting for them.`, link: "" };
}

